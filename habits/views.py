import logging
import phonenumbers
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit
from django_ratelimit.core import is_ratelimited
from typing import Union
from django.http import HttpResponse,  HttpResponseForbidden
from .ai_service import generate_habit_nudge
from .whatsapp import send_whatsapp_message 
from django.conf import settings
from .otp import generate_otp, send_otp, store_otp, verify_otp as verify_otp_code, clear_otp
from .models import Habit, Profile
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_phone_number(raw_phone: str) -> Union[str, None]:
    """
    Parse and normalise a Nigerian phone number to E.164 without the '+'.
    Returns None if the number is invalid.
    """
    try:
        parsed = phonenumbers.parse(raw_phone, "NG")
        if phonenumbers.is_valid_number(parsed):
            return (
                phonenumbers
                .format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                .replace("+", "")
            )
    except phonenumbers.NumberParseException:
        pass
    return None


def _parse_habit(post_data: dict) -> Union[tuple[str, str], tuple[None, None]]: 
    choice = post_data.get("habit_choice", "").strip()
    custom_name = post_data.get("custom_habit", "").strip()

    if choice == "custom":
        if not custom_name:
            return None, None
        return custom_name[:100], "CUSTOM"

    habit_name = dict(Habit.HABIT_CHOICES).get(choice.upper())
    if not habit_name:
        return None, None
    return habit_name, choice.upper()


def banned_check(user) -> bool:
    """Returns True if the user has been deactivated (banned)."""
    return not user.is_active


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------






@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def index(request):
    if request.user.is_authenticated:
        return redirect("habit_list")

    if request.method != "POST":
        return render(request, "habits/index.html")

    raw_phone = request.POST.get("identifier", "").strip()
    clean_number = clean_phone_number(raw_phone)
    if not clean_number:
        messages.error(request, "That phone number is not valid. Please check and try again.")
        return render(request, "habits/index.html")

    if is_ratelimited(request, group="register_phone", key=lambda g, r: clean_number,
                      rate="5/h", method="POST", increment=True):
        messages.error(request, "Too many attempts for this number. Please try again later.")
        return render(request, "habits/index.html")

    password = request.POST.get("password", "")
    if not password:
        messages.error(request, "A password is required.")
        return render(request, "habits/index.html")

    try:
        validate_password(password, user=None)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return render(request, "habits/index.html")

    habit_name, category = _parse_habit(request.POST)
    if not habit_name:
        messages.error(request, "Please select a valid habit.")
        return render(request, "habits/index.html")

    
    if User.objects.filter(username=clean_number).exists():
        messages.info(request, "An account with this number already exists. Please log in.")
        return redirect("login")

    
    request.session['pending_registration'] = {
        'phone': clean_number,
        'password': password,
        'habit_name': habit_name,
        'category': category,
    }

    otp = generate_otp()
    sent = send_otp(clean_number, otp)
    if not sent:
        messages.error(request, "We couldn't send a WhatsApp message to that number. Please check it and try again.")
        return render(request, "habits/index.html")

    store_otp(request, clean_number, otp)
    return redirect("verify_otp")


@ratelimit(key="ip", rate="20/m", method="POST", block=True)
def verify_otp_view(request):
    if request.user.is_authenticated:
        return redirect("habit_list")

    pending = request.session.get('pending_registration')
    if not pending:
        messages.error(request, "Session expired. Please register again.")
        return redirect("index")

    if request.method != "POST":
        return render(request, "habits/verify_otp.html")

    submitted_otp = request.POST.get("otp", "").strip()
    if not submitted_otp:
        messages.error(request, "Please enter the code we sent you.")
        return render(request, "habits/verify_otp.html")

    valid, msg = verify_otp_code(request, pending['phone'], submitted_otp)
    if not valid:
        messages.error(request, msg)
        return render(request, "habits/verify_otp.html")

    
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=pending['phone'], password=pending['password'])
            Profile.objects.create(user=user, phone_number=pending['phone'], is_whatsapp_verified=True)
            Habit.objects.create(user=user, name=pending['habit_name'], category=pending['category'])

    except IntegrityError:
        messages.info(request, "An account with this number already exists. Please log in.")
        return redirect("login")
    except Exception as exc:
        logger.error("Account creation failed after OTP for %s: %s", pending['phone'], exc, exc_info=True)
        messages.error(request, "Something went wrong creating your account. Please try again.")
        return redirect("index")

    request.session.pop('pending_registration', None)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    try:
        send_whatsapp_message(
            pending['phone'],
            "Welcome, I will be your chatbot partner that helps you keep your streak. I will remind you 3 times a day. If you lose your streak for 3 days, you are out. Be warned."
        )
    except Exception as e:
        logger.warning(f"Welcome message failed for {pending['phone']}: {e}")
    return redirect("habit_list")


@ratelimit(key="ip", rate="5/m", method="POST", block=True)
def resend_otp(request):
    pending = request.session.get('pending_registration')
    if not pending:
        messages.error(request, "Session expired. Please register again.")
        return redirect("index")

    otp = generate_otp()
    sent = send_otp(pending['phone'], otp)
    if not sent:
        messages.error(request, "Failed to resend. Please try again.")
        return redirect("verify_otp")

    store_otp(request, pending['phone'], otp)
    messages.success(request, "A new code has been sent to your WhatsApp.")
    return redirect("verify_otp")


# ---------------------------------------------------------------------------
# Login  
# ---------------------------------------------------------------------------

@ratelimit(key="ip", rate="30/m", method="POST", block=True)
def login_view(request):
    if request.user.is_authenticated:
        return redirect("habit_list")

    if request.method == "POST":
        raw_phone = request.POST.get("identifier", "").strip()
        password = request.POST.get("password", "")

        clean_number = clean_phone_number(raw_phone)
        if not clean_number:
            messages.error(request, "That phone number is not valid.")
            return render(request, "habits/login.html")

        
        try:
            existing = User.objects.get(username=clean_number)
            if not existing.is_active:
                return redirect("banned")
        except User.DoesNotExist:
            pass

        user = authenticate(request, username=clean_number, password=password)
        if user is not None:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("habit_list")
        else:
            messages.error(request, "Invalid number or password.")

    return render(request, "habits/login.html")


# ---------------------------------------------------------------------------
# Habit list (dashboard)
# ---------------------------------------------------------------------------

@login_required
def habit_list(request):
    if banned_check(request.user):
        logout(request)
        return redirect("banned")
    


    habits = Habit.objects.filter(user=request.user)
    today = timezone.localdate()
    now = timezone.localtime()
    hour = now.hour

    if 5 <= hour < 12:
        greeting = "Good morning"
    elif 12 <= hour < 17:
        greeting = "Good afternoon"
    elif 17 <= hour < 21:
        greeting = "Good evening"
    else:
        greeting = "Hey, night owl"

    total_streak = sum(h.current_streak for h in habits)
    total_misses = sum(h.missed_count for h in habits)
    max_days_left = max((3 - h.missed_count for h in habits), default=0)
    
    

    
    
    return render(request, "habits/habit_list.html", {"habits": habits, "today": today, "total_streak": total_streak, "total_misses": total_misses, "max_days_left": max_days_left, "greeting": greeting})


# ---------------------------------------------------------------------------
# Mark habit done 
# ---------------------------------------------------------------------------

@login_required
@require_POST
def mark_habit_done(request, habit_id):
    if banned_check(request.user):
        logout(request)
        return JsonResponse({"status": "banned"}, status=403)

    try:
        habit = Habit.objects.get(id=habit_id, user=request.user)
    except Habit.DoesNotExist:
        return JsonResponse({"status": "not_found"}, status=404)

    result = habit.mark_done()
    return JsonResponse(result)




@login_required
@ratelimit(key="user", rate="5/m", method="POST", block=True)
def add_habit(request):
    if banned_check(request.user):
        logger.warning(f"Banned user {request.user.id} attempted to add habit.")
        return redirect("banned")

    if request.method != "POST":
        return render(request, "habits/add_habit.html")

    habit_name, category = _parse_habit(request.POST)
    if not habit_name:
        return HttpResponse("Invalid parameters.", status=400)

    try:
        with transaction.atomic():
            if Habit.objects.filter(user=request.user, name__iexact=habit_name).exists():
                return HttpResponse("You're already working on this habit.", status=400)

            if Habit.objects.filter(user=request.user).count() >= 3:
                return HttpResponse("Max 3 habits. Focus is key.", status=400)

            habit = Habit.objects.create(
                user=request.user,
                name=habit_name,
                category=category,
            )
            logger.info(f"User {request.user.id} created habit: {habit_name}")

            if request.headers.get('HX-Request'):
                return render(request, "habits/partials/habit_card.html", {"habit": habit})

    except Exception as e:
        logger.exception(f"Failure in add_habit for {request.user.id}")
        return HttpResponse("Server error. Try again.", status=500)

    return redirect("habit_list")

# ---------------------------------------------------------------------------
# Banned page
# ---------------------------------------------------------------------------

def banned_view(request):
    return render(request, "habits/banned.html", status=403)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@login_required
def user_logout(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "You have been logged out.")
        return redirect("index")
    return redirect("habit_list")

def lockout_view(request, exception=None):
    return render(request, 'habits/lockout.html', status=403)


# ---------------------------------------------------------------------------
# Maintenance Trigger & Gemini Integration
# ---------------------------------------------------------------------------


def maintenance_trigger(request):
    key = request.GET.get('key')
    if key != settings.MAINTENANCE_KEY:
        return HttpResponseForbidden("Nice try!")

    task = request.GET.get('task', 'send_nudges')  

    now = timezone.localtime()

    
    if task == 'generate_nudges':
        habits = list(
            Habit.objects
            .filter(user__is_active=True)
            .select_related('user__profile')
        )
        success = 0
        failed = 0
        for i, habit in enumerate(habits):
            try:
                nudge = generate_habit_nudge(
                    habit.name,
                    habit.current_streak,
                    habit.missed_count,
                )
                habit.cached_nudge = nudge
                habit.nudge_generated_at = now
                habit.save(update_fields=["cached_nudge", "nudge_generated_at"])
                success += 1
                logger.info("Nudge cached for habit %s: %s", habit.id, nudge)
            except Exception as e:
                failed += 1
                logger.error("Nudge generation failed for habit %s: %s", habit.id, e)

            
            if i < len(habits) - 1:
                time.sleep(4.5)

        return HttpResponse(f"Generated {success}/{len(habits)} nudges. {failed} failed.")


    if task == 'send_nudges':
        hour = now.hour
        if 5 <= hour <= 11:
            task_type = "MORNING GINGER"
        elif 12 <= hour <= 17:
            task_type = "AFTERNOON PUSH"
        else:
            task_type = "DAILY CHECK-IN"

        active_habits = list(
            Habit.objects
            .filter(user__is_active=True)
            .select_related('user__profile')
        )

        user_habits = defaultdict(list)
        for habit in active_habits:
            user_habits[habit.user].append(habit)

        sent = 0
        for user, habits in user_habits.items():
            try:
                habit_blocks = []
                for habit in habits:
                    
                    nudge = habit.cached_nudge or "No allow your fire go out. Stay focused."
                    habit_blocks.append(
                        f"*{habit.name}*\n"
                        f"Streak: {habit.current_streak} days | Misses: {habit.missed_count}/3\n"
                        f"{nudge}"
                    )

                wa_message = f"*{task_type}*\n\n" + "\n\n".join(habit_blocks)
                send_whatsapp_message(user.profile.phone_number, wa_message)
                sent += 1
            except Exception as e:
                logger.error("Send failed for user %s: %s", user.username, e)

        return HttpResponse(f"Sent to {sent}/{len(user_habits)} users.")
    if task == 'night_watch':
        today = now.date()
        yesterday = today - timezone.timedelta(days=1)

        
        stale_habits = list(
            Habit.objects
            .filter(user__is_active=True, last_marked_date__lt=yesterday)
            .exclude(last_marked_date=None)
            .select_related('user__profile')
        )

        banned_count = 0
        for habit in stale_habits:
            result = habit.record_miss()
            if result["status"] == "banned":
                banned_count += 1
                logger.warning("User %s banned after 3 misses.", habit.user.username)

        
        active_habits = list(
            Habit.objects
            .filter(user__is_active=True)
            .select_related('user__profile')
        )

        user_habits = defaultdict(list)
        for habit in active_habits:
            user_habits[habit.user].append(habit)

        sent = 0
        for user, habits in user_habits.items():
            try:
                habit_blocks = []
                for habit in habits:
                    nudge = habit.cached_nudge or "No allow your fire go out. Stay focused."
                    habit_blocks.append(
                        f"*{habit.name}*\n"
                        f"Streak: {habit.current_streak} days | Misses: {habit.missed_count}/3\n"
                        f"{nudge}"
                    )

                wa_message = "*NIGHT WATCH*\n\n" + "\n\n".join(habit_blocks)
                send_whatsapp_message(user.profile.phone_number, wa_message)
                sent += 1
            except Exception as e:
                logger.error("Night send failed for user %s: %s", user.username, e)

        return HttpResponse(
            f"Night watch done. {len(stale_habits)} misses recorded. "
            f"{banned_count} banned. {sent}/{len(user_habits)} messages sent."
        )

    return HttpResponseForbidden(f"Unknown task: {task}")
