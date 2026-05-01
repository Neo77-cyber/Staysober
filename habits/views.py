import logging
import time
from collections import defaultdict
import hmac

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST


from django_ratelimit.decorators import ratelimit
from django_ratelimit.core import is_ratelimited


from .models import Habit, Profile
from .services.ai_service import generate_habit_nudge, FALLBACK_NUDGES 
from .services.helpers import clean_phone_number, parse_habit, banned_check
from .services.otp import generate_otp, send_otp, store_otp, verify_otp as verify_otp_code, clear_otp
from .services.whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authentication
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
        messages.error(request, "Phone number is invalid. Please remove the '0' before your number (e.g. 8123 not 08123).")
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
 
    
    email = request.POST.get("email", "").strip().lower()
 
    habit_name, category = parse_habit(request.POST)
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
        'email': email,
    }
    request.session.modified = True
    request.session.save()
 
    otp = generate_otp()
    sent, method = send_otp(clean_number, otp, email=email or None)
 
    if not sent:
        
        if not email:
            messages.error(request,
                "We couldn't reach that number on WhatsApp. "
                "Add your email address and we'll send the code there instead."
            )
        else:
            messages.error(request, "We couldn't send a verification code. Please try again.")
        return render(request, "habits/index.html")
 
    
    request.session['otp_method'] = method
    store_otp(request, clean_number, otp, method=method)
 
    if method == "email":
        messages.info(request,
            f"WhatsApp is currently at capacity. We sent your code to {email} instead."
        )
 
    return redirect("verify_otp")
 
 
# --- verify_otp_view ---
 
@ratelimit(key="ip", rate="5/m", method="POST", block=True)
def verify_otp_view(request):
    if request.user.is_authenticated:
        return redirect("habit_list")

    pending = request.session.get('pending_registration')
    if not pending:
        messages.error(request, "Session expired. Please register again.")
        return redirect("index")

    otp_method = request.session.get('otp_method', 'whatsapp')

    if request.method != "POST":
        return render(request, "habits/verify_otp.html", {"otp_method": otp_method})

    submitted_otp = request.POST.get("otp", "").strip()
    if not submitted_otp:
        messages.error(request, "Please enter the code we sent you.")
        return render(request, "habits/verify_otp.html", {"otp_method": otp_method})

    valid, msg = verify_otp_code(request, pending['phone'], submitted_otp)
    if not valid:
        messages.error(request, msg)
        return render(request, "habits/verify_otp.html", {"otp_method": otp_method})

    
    phone = pending['phone']
    password = pending['password']
    email = pending.get('email', '')
    habit_name = pending['habit_name']
    category = pending['category']

    request.session.pop('pending_registration', None)
    request.session.pop('otp_method', None)
    request.session.save()

    
    if User.objects.filter(username=phone).exists():
        messages.info(request, "An account with this number already exists. Please log in.")
        return redirect("login")

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=phone,
                password=password,
                email=email,
            )
            Profile.objects.create(
                user=user,
                phone_number=phone,
                is_whatsapp_verified=(otp_method == 'whatsapp'),
            )
            Habit.objects.create(
                user=user,
                name=habit_name,
                category=category,
            )

    except IntegrityError:
       
        logger.warning("IntegrityError on account creation for %s — possible race", phone)
        messages.info(request, "An account with this number already exists. Please log in.")
        return redirect("login")
    except Exception as exc:
        logger.error("Account creation failed after OTP for %s: %s", phone, exc, exc_info=True)
        messages.error(request, "Something went wrong. Please try again.")
        return redirect("index")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    if otp_method == 'whatsapp':
        try:
            send_whatsapp_message(
                phone,
                "Welcome to DearSelf. I will remind you 3 times a day. "
                "Miss 3 days and you are out. Let's go."
            )
        except Exception as e:
            logger.warning("Welcome message failed for %s: %s", phone[:4], e)

    return redirect("habit_list")
 
 
# --- resend_otp ---
 
@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def resend_otp(request):
    pending = request.session.get('pending_registration')
    if not pending:
        messages.error(request, "Session expired. Please register again.")
        return redirect("index")
 
    otp = generate_otp()
    sent, method = send_otp(pending['phone'], otp, email=pending.get('email') or None)
 
    if not sent:
        messages.error(request, "Failed to resend. Please try again.")
        return redirect("verify_otp")
 
    request.session['otp_method'] = method
    store_otp(request, pending['phone'], otp, method=method)
 
    if method == "email":
        messages.success(request, f"Code resent to {pending.get('email', 'your email')}.")
    else:
        messages.success(request, "A new code has been sent to your WhatsApp.")
 
    return redirect("verify_otp")



# ---------------------------------------------------------------------------
# Login  
# ---------------------------------------------------------------------------

@ratelimit(key="ip", rate="10/m", method="POST", block=True)
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

        
        if is_ratelimited(request, group="login_user", key=lambda g, r: clean_number,
                        rate="5/h", method="POST", increment=True):
            messages.error(request, "Too many failed login attempts for this number. Try again in an hour.")
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
# Habit list (dashboard)
# ---------------------------------------------------------------------------

@login_required
def habit_list(request):
    if banned_check(request.user):
        logout(request)
        return redirect("banned")

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

    

    habits = Habit.objects.filter(user=request.user).only(
        'id', 'name', 'category', 'current_streak',
        'missed_count', 'last_marked_date', 'cached_nudge'
    )

    total_streak = sum(h.current_streak for h in habits)
    total_misses = sum(h.missed_count for h in habits)
    max_days_left = max((3 - h.missed_count for h in habits), default=0)

    return render(request, "habits/habit_list.html", {
        "habits": habits,
        "today": today,
        "total_streak": total_streak,
        "total_misses": total_misses,
        "max_days_left": max_days_left,
        "greeting": greeting,
    })


# ---------------------------------------------------------------------------
# Mark habit done 
# ---------------------------------------------------------------------------

@login_required
@require_POST
@ratelimit(key="user", rate="30/m", method="POST", block=True)
def mark_habit_done(request, habit_id):
    if banned_check(request.user):
        logout(request)
        return JsonResponse({"status": "banned"}, status=403)

    try:
        habit = Habit.objects.get(id=habit_id, user=request.user)
    except Habit.DoesNotExist:
        return JsonResponse({"status": "not_found"}, status=404)

    result = habit.mark_done()

    total_streak = sum(
        h.current_streak for h in Habit.objects.filter(user=request.user)
    )
    result["total_streak"] = total_streak
    return JsonResponse(result)



# ---------------------------------------------------------------------------
# Add Habit
# ---------------------------------------------------------------------------

@login_required
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def add_habit(request):
    if banned_check(request.user):
        logger.warning(f"Banned user {request.user.id} attempted to add habit.")
        return redirect("banned")

    if request.method != "POST":
        return render(request, "habits/add_habit.html")

    habit_name, category = parse_habit(request.POST)
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
# Maintenance Trigger & Gemini Integration
# ---------------------------------------------------------------------------


@require_POST
def maintenance_trigger(request):
    key = request.headers.get('X-Maintenance-Key') or request.POST.get('key')

    if not key or not hmac.compare_digest(key, settings.MAINTENANCE_KEY):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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
        fallback_used = 0
        lines = []

        for i, habit in enumerate(habits):
            try:
                nudge = generate_habit_nudge(
                    habit.name,
                    habit.current_streak,
                    habit.missed_count,
                )

                
                is_fallback = nudge in [
                    "No allow your fire go out. Stay focused.",
                    "You don start, no go back now. Finish what you started.",
                    "Every day you hold on, you dey win. Keep going.",
                    "Your future self go thank you. Do am for am.",
                    "The goal no go chase itself. You must move.",
                ]

                habit.cached_nudge = nudge
                habit.nudge_generated_at = now
                habit.save(update_fields=["cached_nudge", "nudge_generated_at"])

                if is_fallback:
                    fallback_used += 1
                    lines.append(f"  {habit.name}: FALLBACK — {nudge}")
                else:
                    success += 1
                    lines.append(f"  {habit.name}: {nudge}")

                logger.info("Habit %s nudge: %s (fallback=%s)", habit.id, nudge, is_fallback)

            except Exception as e:
                failed += 1
                lines.append(f"  {habit.name}: ERROR — {e}")
                logger.error("Nudge generation failed for habit %s: %s", habit.id, e)

            if i < len(habits) - 1:
                time.sleep(10)

        summary = (
            f"Generated {success}/{len(habits)} real nudges. "
            f"{fallback_used} fallbacks. {failed} errors.\n\n"
            + "\n".join(lines)
        )
        logger.info(summary)
        return HttpResponse(summary, content_type="text/plain")
    
    DASHBOARD_URL = "https://dear-self.onrender.com/habits/"


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
                    
                    nudge = habit.cached_nudge or FALLBACK_NUDGES[habit.id % len(FALLBACK_NUDGES)]
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
                    nudge = habit.cached_nudge or FALLBACK_NUDGES[habit.id % len(FALLBACK_NUDGES)]
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

    if task == 'debug_nudges':
        habits = Habit.objects.filter(user__is_active=True).select_related('user__profile')
        lines = []
        for h in habits:
            lines.append(
                f"Habit: {h.name} | "
                f"cached_nudge: '{h.cached_nudge}' | "
                f"generated_at: {h.nudge_generated_at}"
            )
        return HttpResponse("\n".join(lines), content_type="text/plain")

    return HttpResponseForbidden(f"Unknown task: {task}")

def health_check(request):
    return HttpResponse("ok", status=200)
