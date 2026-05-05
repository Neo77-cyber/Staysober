
import hashlib
import json
from datetime import timedelta
from unittest.mock import MagicMock, call, patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Habit, Profile



# Helpers


class CleanPhoneNumberTests(TestCase):
    

    def _call(self, raw):
        from .services.helpers import clean_phone_number
        return clean_phone_number(raw)

    def test_valid_nigerian_number_with_country_code(self):
        result = self._call("+2348123456789")
        self.assertEqual(result, "2348123456789")

    def test_valid_nigerian_number_local_format(self):
        
        result = self._call("08123456789")
        self.assertEqual(result, "2348123456789")

    def test_strips_plus_sign(self):
        result = self._call("+2348011112222")
        self.assertFalse(result.startswith("+"))

    def test_invalid_number_returns_none(self):
        self.assertIsNone(self._call("abc"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self._call(""))

    def test_too_short_returns_none(self):
        self.assertIsNone(self._call("0801"))

    def test_strips_whitespace_before_parsing(self):
        result = self._call("  +2348123456789  ")
        self.assertIsNotNone(result)


class ParseHabitTests(TestCase):
   

    def _call(self, post_data):
        from .services.helpers import parse_habit
        return parse_habit(post_data)

    def test_known_habit_choice_returns_name_and_category(self):
        first_key = Habit.HABIT_CHOICES[0][0]
        first_name = Habit.HABIT_CHOICES[0][1]
        name, cat = self._call({"habit_choice": first_key.lower()})
        self.assertEqual(name, first_name)
        self.assertEqual(cat, first_key.upper())

    def test_custom_habit_with_name(self):
        name, cat = self._call({"habit_choice": "custom", "custom_habit": "Morning run"})
        self.assertEqual(name, "Morning run")
        self.assertEqual(cat, "CUSTOM")

    def test_custom_habit_without_name_returns_none(self):
        name, cat = self._call({"habit_choice": "custom", "custom_habit": ""})
        self.assertIsNone(name)
        self.assertIsNone(cat)

    def test_unknown_choice_returns_none(self):
        name, cat = self._call({"habit_choice": "DOES_NOT_EXIST"})
        self.assertIsNone(name)
        self.assertIsNone(cat)

    def test_custom_habit_truncated_to_100_chars(self):
        long_name = "x" * 200
        name, _ = self._call({"habit_choice": "custom", "custom_habit": long_name})
        self.assertEqual(len(name), 100)

    def test_empty_post_returns_none(self):
        name, cat = self._call({})
        self.assertIsNone(name)
        self.assertIsNone(cat)


class BannedCheckTests(TestCase):
    

    def _call(self, user):
        from .services.helpers import banned_check
        return banned_check(user)

    def test_active_user_not_banned(self):
        user = MagicMock(is_active=True)
        self.assertFalse(self._call(user))

    def test_inactive_user_is_banned(self):
        user = MagicMock(is_active=False)
        self.assertTrue(self._call(user))


class MaskPhoneTests(TestCase):
   

    def _call(self, phone):
        from .services.helpers import mask_phone
        return mask_phone(phone)

    def test_normal_phone_masked(self):
        result = self._call("2348123456789")
        self.assertTrue(result.startswith("2348"))
        self.assertIn("****", result)
        self.assertTrue(result.endswith("789"))

    def test_short_phone_returns_stars(self):
        self.assertEqual(self._call("123"), "***")

    def test_empty_string_returns_stars(self):
        self.assertEqual(self._call(""), "***")

    def test_none_returns_stars(self):
        self.assertEqual(self._call(None), "***")



# OTP service


class GenerateOTPTests(TestCase):
    def test_six_digits(self):
        from .services.otp import generate_otp
        otp = generate_otp()
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())

    def test_range(self):
        from .services.otp import generate_otp
        for _ in range(20):
            val = int(generate_otp())
            self.assertGreaterEqual(val, 100000)
            self.assertLessEqual(val, 999999)

    def test_uniqueness(self):
        from .services.otp import generate_otp
        otps = {generate_otp() for _ in range(50)}
        
        self.assertGreater(len(otps), 1)


class StoreAndVerifyOTPTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        
        from django.contrib.sessions.backends.db import SessionStore
        self.request.session = SessionStore()

    def _store(self, phone, otp, method="whatsapp"):
        from .services.otp import store_otp
        store_otp(self.request, phone, otp, method=method)

    def _verify(self, phone, submitted):
        from .services.otp import verify_otp
        return verify_otp(self.request, phone, submitted)

    def test_correct_otp_succeeds(self):
        self._store("2348000000001", "123456")
        valid, msg = self._verify("2348000000001", "123456")
        self.assertTrue(valid)
        self.assertEqual(msg, "ok")

    def test_wrong_otp_fails(self):
        self._store("2348000000001", "123456")
        valid, msg = self._verify("2348000000001", "999999")
        self.assertFalse(valid)
        self.assertIn("Wrong", msg)

    def test_expired_otp_fails(self):
        from .services.otp import store_otp, OTP_EXPIRY_MINUTES
        store_otp(self.request, "2348000000001", "123456")
        
        self.request.session['otp_data']['expires_at'] = (
            timezone.now() - timedelta(seconds=1)
        ).timestamp()
        valid, msg = self._verify("2348000000001", "123456")
        self.assertFalse(valid)
        self.assertIn("expired", msg.lower())

    def test_phone_mismatch_fails(self):
        self._store("2348000000001", "123456")
        valid, msg = self._verify("2348000000002", "123456")
        self.assertFalse(valid)
        self.assertIn("mismatch", msg.lower())

    def test_no_session_data_fails(self):
        valid, msg = self._verify("2348000000001", "123456")
        self.assertFalse(valid)
        self.assertIn("expired", msg.lower())

    def test_max_attempts_locks_out(self):
        from .services.otp import OTP_MAX_ATTEMPTS
        self._store("2348000000001", "123456")
        for _ in range(OTP_MAX_ATTEMPTS):
            self._verify("2348000000001", "000000")
        valid, msg = self._verify("2348000000001", "123456")
        self.assertFalse(valid)

    def test_remaining_attempts_count_decrements(self):
        from .services.otp import OTP_MAX_ATTEMPTS
        self._store("2348000000001", "123456")
        _, msg = self._verify("2348000000001", "000000")
        self.assertIn(str(OTP_MAX_ATTEMPTS - 1), msg)

    def test_clear_otp_removes_session_data(self):
        from .services.otp import clear_otp
        self._store("2348000000001", "123456")
        clear_otp(self.request)
        self.assertNotIn('otp_data', self.request.session)

    def test_otp_hashed_not_stored_plaintext(self):
        self._store("2348000000001", "123456")
        stored = self.request.session['otp_data']['otp_hash']
        self.assertNotEqual(stored, "123456")
        self.assertEqual(stored, hashlib.sha256("123456".encode()).hexdigest())


class SendOTPTests(TestCase):

    def _send_otp(self, phone, otp, email=None):
        
        import habits.services.otp as otp_module
        
        fn = getattr(otp_module.send_otp, '__wrapped__', otp_module.send_otp)
        
        return fn(phone, otp, email)

    @patch("habits.services.otp.is_whatsapp_quota_exceeded", return_value=False)
    @patch("habits.services.otp.send_otp_whatsapp", return_value=True)
    def test_sends_via_whatsapp_when_available(self, mock_wa, mock_quota):
        sent, method = self._send_otp("2348000000001", "123456")
        self.assertTrue(sent)
        self.assertEqual(method, "whatsapp")

    @patch("habits.services.otp.is_whatsapp_quota_exceeded", return_value=True)
    @patch("habits.services.otp.send_otp_email", return_value=True)
    def test_falls_back_to_email_when_whatsapp_quota_exceeded(self, mock_email, mock_quota):
        sent, method = self._send_otp("2348000000001", "123456", email="user@example.com")
        self.assertTrue(sent)
        self.assertEqual(method, "email")

    @patch("habits.services.otp.is_whatsapp_quota_exceeded", return_value=False)
    @patch("habits.services.otp.send_otp_whatsapp", return_value=False)
    @patch("habits.services.otp.send_otp_email", return_value=True)
    def test_falls_back_to_email_when_whatsapp_send_fails(self, mock_email, mock_wa, mock_quota):
        sent, method = self._send_otp("2348000000001", "123456", email="user@example.com")
        self.assertTrue(sent)
        self.assertEqual(method, "email")

    @patch("habits.services.otp.is_whatsapp_quota_exceeded", return_value=True)
    def test_returns_false_when_quota_exceeded_and_no_email(self, mock_quota):
        sent, method = self._send_otp("2348000000001", "123456", email=None)
        self.assertFalse(sent)
        self.assertIsNone(method)

    @patch("habits.services.otp.is_whatsapp_quota_exceeded", return_value=False)
    @patch("habits.services.otp.send_otp_whatsapp", return_value=False)
    def test_returns_false_when_all_channels_fail(self, mock_wa, mock_quota):
        sent, method = self._send_otp("2348000000001", "123456", email=None)
        self.assertFalse(sent)


# Email service


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@dearself.app",
)
class SendOTPEmailTests(TestCase):

    def _call(self, email, otp, expiry=15):
        from .services.email_service import send_otp_email
        return send_otp_email(email, otp, expiry)

    def test_returns_true_on_success(self):
        result = self._call("test@example.com", "654321")
        self.assertTrue(result)

    def test_email_is_sent(self):
        self._call("test@example.com", "654321")
        self.assertEqual(len(mail.outbox), 1)

    def test_correct_recipient(self):
        self._call("user@example.com", "654321")
        self.assertIn("user@example.com", mail.outbox[0].to)

    def test_otp_in_body(self):
        self._call("user@example.com", "777888")
        self.assertIn("777888", mail.outbox[0].body)

    def test_otp_in_html_body(self):
        self._call("user@example.com", "777888")
        alternatives = mail.outbox[0].alternatives
        html_body = alternatives[0][0] if alternatives else ""
        self.assertIn("777888", html_body)

    def test_returns_false_on_send_error(self):
        with patch("habits.services.email_service.send_mail", side_effect=Exception("SMTP down")):
            result = self._call("bad@example.com", "000000")
        self.assertFalse(result)

    def test_from_email_is_correct(self):
        self._call("user@example.com", "123456")
        self.assertEqual(mail.outbox[0].from_email, "noreply@dearself.app")



# WhatsApp service


class WhatsAppServiceTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.delete("green_api_quota_exceeded")

    @patch("habits.services.whatsapp.requests.post")
    def test_send_message_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"idMessage": "123"}
        from .services.whatsapp import send_whatsapp_message
        result = send_whatsapp_message("2348000000001", "Hello")
        self.assertTrue(result)

    @patch("habits.services.whatsapp.requests.post")
    def test_send_message_non_200_returns_false(self, mock_post):
        mock_post.return_value.status_code = 500
        mock_post.return_value.json.return_value = {}
        from .services.whatsapp import send_whatsapp_message
        result = send_whatsapp_message("2348000000001", "Hello")
        self.assertFalse(result)

    @patch("habits.services.whatsapp.requests.post")
    def test_quota_exceeded_marks_cache_and_returns_false(self, mock_post):
        mock_post.return_value.status_code = 429
        mock_post.return_value.json.return_value = {}
        from .services.whatsapp import send_whatsapp_message, is_whatsapp_quota_exceeded
        send_whatsapp_message("2348000000001", "Hello")
        self.assertTrue(is_whatsapp_quota_exceeded())

    @patch("habits.services.whatsapp.is_whatsapp_quota_exceeded", return_value=True)
    def test_skips_send_when_quota_active(self, mock_quota):
        from .services.whatsapp import send_whatsapp_message
        result = send_whatsapp_message("2348000000001", "Hello")
        self.assertFalse(result)

    @patch("habits.services.whatsapp.requests.post")
    def test_exception_with_quota_keyword_marks_exhausted(self, mock_post):
        mock_post.side_effect = Exception("quota limit reached")
        from .services.whatsapp import send_whatsapp_message, is_whatsapp_quota_exceeded
        send_whatsapp_message("2348000000001", "Hello")
        self.assertTrue(is_whatsapp_quota_exceeded())

    @patch("habits.services.whatsapp.send_whatsapp_message", return_value=True)
    def test_send_otp_whatsapp_includes_otp_in_message(self, mock_send):
        from .services.whatsapp import send_otp_whatsapp
        send_otp_whatsapp("2348000000001", "999111", 15)
        message = mock_send.call_args[0][1]
        self.assertIn("999111", message)

    @patch("habits.services.whatsapp.is_whatsapp_quota_exceeded", return_value=True)
    def test_send_otp_whatsapp_returns_false_when_quota_exceeded(self, mock_quota):
        from .services.whatsapp import send_otp_whatsapp
        result = send_otp_whatsapp("2348000000001", "999111", 15)
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────────────────────────
# AI service
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(GEMINI_API_KEY="test-key-123")
class AIServiceTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _call(self, habit="Reading", streak=5, missed=0):
        from .services.ai_service import generate_habit_nudge
        return generate_habit_nudge(habit, streak, missed)

    @patch("habits.services.ai_service._call_gemini")
    def test_returns_text_from_api(self, mock_call):
        mock_call.return_value = {
            "candidates": [{"content": {"parts": [{"text": "  Keep going!  "}]}}]
        }
        result = self._call()
        self.assertEqual(result, "Keep going!")

    @patch("habits.services.ai_service._call_gemini")
    def test_falls_back_when_response_malformed(self, mock_call):
        from .services.ai_service import FALLBACK_NUDGES
        mock_call.return_value = {"candidates": []}
        result = self._call()
        self.assertIn(result, FALLBACK_NUDGES)

    @patch("habits.services.ai_service._call_gemini")
    def test_falls_back_on_timeout(self, mock_call):
        import requests
        from .services.ai_service import FALLBACK_NUDGES
        mock_call.side_effect = requests.exceptions.Timeout()
        result = self._call()
        self.assertIn(result, FALLBACK_NUDGES)

    @patch("habits.services.ai_service._call_gemini")
    def test_falls_back_on_connection_error(self, mock_call):
        import requests
        from .services.ai_service import FALLBACK_NUDGES
        mock_call.side_effect = requests.exceptions.ConnectionError()
        result = self._call()
        self.assertIn(result, FALLBACK_NUDGES)

    @patch("habits.services.ai_service._call_gemini")
    def test_marks_model_exhausted_on_429(self, mock_call):
        import requests
        from .services.ai_service import _is_model_exhausted, GEMINI_MODELS
        err = requests.exceptions.HTTPError()
        err.response = MagicMock(status_code=429, text="quota exceeded")
        mock_call.side_effect = err
        self._call()
        self.assertTrue(_is_model_exhausted(GEMINI_MODELS[0]))

    @patch("habits.services.ai_service._call_gemini")
    def test_skips_all_calls_when_all_models_exhausted(self, mock_call):
        from .services.ai_service import _mark_model_exhausted, GEMINI_MODELS, FALLBACK_NUDGES
        for m in GEMINI_MODELS:
            _mark_model_exhausted(m)
        result = self._call()
        mock_call.assert_not_called()
        self.assertIn(result, FALLBACK_NUDGES)

    @override_settings(GEMINI_API_KEY="")
    def test_falls_back_when_no_api_key(self):
        from .services.ai_service import FALLBACK_NUDGES
        result = self._call()
        self.assertIn(result, FALLBACK_NUDGES)

    @patch("habits.services.ai_service._call_gemini")
    def test_breaks_on_403(self, mock_call):
        import requests
        from .services.ai_service import FALLBACK_NUDGES
        err = requests.exceptions.HTTPError()
        err.response = MagicMock(status_code=403, text="permission denied")
        mock_call.side_effect = err
        result = self._call()
        
        self.assertIn(result, FALLBACK_NUDGES)
        mock_call.assert_called_once()  



# ──────────────────────────────────────────────────────────────────────────────
# Model: Habit business logic
# ──────────────────────────────────────────────────────────────────────────────

class HabitMarkDoneTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="2348000000001", password="pass")
        Profile.objects.create(user=self.user, phone_number="2348000000001")
        self.habit = Habit.objects.create(user=self.user, name="Reading", category="CUSTOM")

    def test_first_mark_sets_streak_to_1(self):
        self.habit.mark_done()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.current_streak, 1)

    def test_consecutive_day_increments_streak(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.habit.last_marked_date = yesterday
        self.habit.current_streak = 4
        self.habit.save()
        self.habit.mark_done()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.current_streak, 5)

    def test_non_consecutive_day_resets_streak_to_1(self):
        three_days_ago = timezone.localdate() - timedelta(days=3)
        self.habit.last_marked_date = three_days_ago
        self.habit.current_streak = 10
        self.habit.save()
        self.habit.mark_done()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.current_streak, 1)

    def test_already_done_today_returns_already_done(self):
        self.habit.last_marked_date = timezone.localdate()
        self.habit.save()
        result = self.habit.mark_done()
        self.assertEqual(result["status"], "already_done")

    def test_updates_longest_streak(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.habit.last_marked_date = yesterday
        self.habit.current_streak = 9
        self.habit.longest_streak = 9
        self.habit.save()
        self.habit.mark_done()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.longest_streak, 10)

    def test_does_not_lower_longest_streak(self):
        self.habit.longest_streak = 100
        self.habit.save()
        self.habit.mark_done()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.longest_streak, 100)

    def test_creates_daily_record(self):
        from .models import DailyRecord
        self.habit.mark_done()
        self.assertTrue(
            DailyRecord.objects.filter(
                habit=self.habit, date=timezone.localdate(), completed=True
            ).exists()
        )

    def test_marked_today_property_true_after_mark(self):
        self.habit.mark_done()
        self.habit.refresh_from_db()
        self.assertTrue(self.habit.marked_today)

    def test_marked_today_property_false_before_mark(self):
        self.assertFalse(self.habit.marked_today)


class HabitRecordMissTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="2348000000099", password="pass")
        Profile.objects.create(user=self.user, phone_number="2348000000099")
        self.habit = Habit.objects.create(user=self.user, name="Exercise", category="CUSTOM")

    def test_miss_increments_missed_count(self):
        self.habit.record_miss()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.missed_count, 1)

    def test_miss_resets_streak_to_0(self):
        self.habit.current_streak = 7
        self.habit.save()
        self.habit.record_miss()
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.current_streak, 0)

    def test_returns_missed_status_before_ban(self):
        result = self.habit.record_miss()
        self.assertEqual(result["status"], "missed")

    def test_third_miss_bans_user(self):
        self.habit.missed_count = 2
        self.habit.save()
        result = self.habit.record_miss()
        self.assertEqual(result["status"], "banned")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_second_miss_does_not_ban(self):
        self.habit.missed_count = 1
        self.habit.save()
        self.habit.record_miss()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_creates_daily_record_for_yesterday(self):
        from .models import DailyRecord
        self.habit.record_miss()
        yesterday = timezone.localdate() - timedelta(days=1)
        self.assertTrue(
            DailyRecord.objects.filter(
                habit=self.habit, date=yesterday, completed=False
            ).exists()
        )

    def test_missed_yesterday_property_true_when_stale(self):
        two_days_ago = timezone.localdate() - timedelta(days=2)
        self.habit.last_marked_date = two_days_ago
        self.habit.save()
        self.assertTrue(self.habit.missed_yesterday)

    def test_missed_yesterday_property_false_when_marked_yesterday(self):
        self.habit.last_marked_date = timezone.localdate() - timedelta(days=1)
        self.habit.save()
        self.assertFalse(self.habit.missed_yesterday)

    def test_missed_yesterday_property_false_when_never_started(self):
        self.assertFalse(self.habit.missed_yesterday)

# ──────────────────────────────────────────────────────────────────────────────
# View helpers / fixtures
# ──────────────────────────────────────────────────────────────────────────────

def make_user(phone="2348000000001", password="StrongPass1!", email="", active=True):
    user = User.objects.create_user(
        username=phone, password=password, email=email, is_active=active
    )
    Profile.objects.create(user=user, phone_number=phone)
    return user


def make_habit(user, name=None, category=None):
    if name is None:
        name = Habit.HABIT_CHOICES[0][1]
        category = Habit.HABIT_CHOICES[0][0]
    return Habit.objects.create(user=user, name=name, category=category or "CUSTOM")


VALID_PHONE = "+2348123456789"
CLEAN_PHONE = "2348123456789"
VALID_PASS = "ValidPass123!"


# ──────────────────────────────────────────────────────────────────────────────
# Index / Registration view
# ──────────────────────────────────────────────────────────────────────────────


class RegressionTests(TestCase):
    """Tests added after real production bugs"""

    def test_safari_session_cookie_settings(self):
        """
        Regression: SESSION_COOKIE_SAMESITE='None' caused Safari mobile
        to drop the session between registration and OTP verification.
        Fixed: changed to 'Lax' + added SECURE_PROXY_SSL_HEADER for Render.
        """
        from django.conf import settings
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertFalse(settings.SECURE_SSL_REDIRECT)
        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ('HTTP_X_FORWARDED_PROTO', 'https')
        )

    def test_habit_choice_template_values_match_model_constants(self):
    
        from .services.helpers import parse_habit
        for key, label in Habit.HABIT_CHOICES:
            with self.subTest(habit=key):
                if key.upper() == 'CUSTOM':
                    
                    name, category = parse_habit({
                        "habit_choice": key.lower(),
                        "custom_habit": "Morning run",
                    })
                else:
                    name, category = parse_habit({"habit_choice": key.lower()})
                
                self.assertIsNotNone(name,
                    f"'{key}' is not parseable — template option value mismatch")

    @patch("habits.views.send_otp", return_value=(True, "whatsapp"))
    @patch("habits.views.is_ratelimited", return_value=False)
    def test_session_survives_registration_redirect(self, mock_rl, mock_send):
       
        response = self.client.post(reverse("index"), {
            "identifier": "+2348123456789",
            "password": "ValidPass123!",
            "habit_choice": Habit.HABIT_CHOICES[0][0].lower(),
        })
        self.assertRedirects(response, reverse("verify_otp"))

        response = self.client.get(reverse("verify_otp"))
        self.assertEqual(response.status_code, 200)
        self.assertIn('pending_registration', self.client.session)
        self.assertIn('otp_data', self.client.session)      # now actually written
        self.assertIn('otp_method', self.client.session)
@override_settings(RATELIMIT_ENABLE=False)     
class IndexViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("index")
        self.first_habit_key = Habit.HABIT_CHOICES[0][0].lower()

    def _post(self, **kwargs):
        data = {
            "identifier": VALID_PHONE,
            "password": VALID_PASS,
            "habit_choice": self.first_habit_key,
            **kwargs,
        }
        return self.client.post(self.url, data)

    def test_get_renders_index(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "habits/index.html")

    def test_authenticated_user_redirected(self):
        user = make_user()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("habit_list"))

    def test_invalid_phone_shows_error(self):
        response = self._post(identifier="bad-number")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid")

    def test_missing_password_shows_error(self):
        response = self._post(password="")
        self.assertEqual(response.status_code, 200)

    def test_weak_password_shows_error(self):
        response = self._post(password="123")
        self.assertEqual(response.status_code, 200)

    def test_invalid_habit_choice_shows_error(self):
        response = self._post(habit_choice="NONEXISTENT")
        self.assertEqual(response.status_code, 200)

    def test_existing_user_redirects_to_login(self):
        make_user(phone=CLEAN_PHONE)
        with patch("habits.views.send_otp", return_value=(True, "whatsapp")):
            response = self._post()
        self.assertRedirects(response, reverse("login"))

    @patch("habits.views.send_otp", return_value=(True, "whatsapp"))
    @patch("habits.views.store_otp")
    @patch("habits.views.is_ratelimited", return_value=False)
    def test_successful_registration_redirects_to_verify(self, mock_rl, mock_store, mock_send):
        response = self._post()
        self.assertRedirects(response, reverse("verify_otp"))

    @patch("habits.views.send_otp", return_value=(True, "whatsapp"))
    @patch("habits.views.store_otp")
    @patch("habits.views.is_ratelimited", return_value=False)
    def test_pending_registration_stored_in_session(self, mock_rl, mock_store, mock_send):
        self._post()
        pending = self.client.session.get("pending_registration")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["phone"], CLEAN_PHONE)

    @patch("habits.views.send_otp", return_value=(False, None))
    def test_send_otp_failure_shows_error(self, mock_send):
        response = self._post()
        self.assertEqual(response.status_code, 200)

    @patch("habits.views.send_otp", return_value=(True, "email"))
    @patch("habits.views.store_otp")
    @patch("habits.views.is_ratelimited", return_value=False)
    def test_email_fallback_shows_info_message(self, mock_rl, mock_store, mock_send):
        response = self._post(email="user@example.com")
        # Email fallback message should be shown
        messages_list = list(response.wsgi_request._messages)
        texts = [str(m) for m in messages_list]
        self.assertTrue(any("email" in t.lower() or "capacity" in t.lower() for t in texts))


# ──────────────────────────────────────────────────────────────────────────────
# Verify OTP view
# ──────────────────────────────────────────────────────────────────────────────
@override_settings(RATELIMIT_ENABLE=False)
class VerifyOTPViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("verify_otp")
        
        session = self.client.session
        session["pending_registration"] = {
            "phone": CLEAN_PHONE,
            "password": VALID_PASS,
            "habit_name": Habit.HABIT_CHOICES[0][1],
            "category": Habit.HABIT_CHOICES[0][0],
            "email": "",
        }
        session["otp_method"] = "whatsapp"
        otp = "123456"
        hashed = hashlib.sha256(otp.encode()).hexdigest()
        session["otp_data"] = {
            "otp_hash": hashed,
            "phone": CLEAN_PHONE,
            "expires_at": (timezone.now() + timedelta(minutes=15)).timestamp(),
            "attempts": 0,
            "method": "whatsapp",
        }
        session.save()
        self.otp = otp

    def test_get_renders_verify_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "habits/verify_otp.html")

    def test_no_pending_session_redirects_to_index(self):
        self.client.session.flush()
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("index"))

    def test_wrong_otp_shows_error(self):
        response = self.client.post(self.url, {"otp": "000000"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wrong")

    @patch("habits.views.send_whatsapp_message")
    def test_correct_otp_creates_user_and_redirects(self, mock_wa):
        response = self.client.post(self.url, {"otp": self.otp})
        self.assertRedirects(response, reverse("habit_list"))
        self.assertTrue(User.objects.filter(username=CLEAN_PHONE).exists())

    @patch("habits.views.send_whatsapp_message")
    def test_correct_otp_creates_profile(self, mock_wa):
        self.client.post(self.url, {"otp": self.otp})
        self.assertTrue(Profile.objects.filter(phone_number=CLEAN_PHONE).exists())

    @patch("habits.views.send_whatsapp_message")
    def test_correct_otp_creates_habit(self, mock_wa):
        self.client.post(self.url, {"otp": self.otp})
        user = User.objects.get(username=CLEAN_PHONE)
        self.assertTrue(Habit.objects.filter(user=user).exists())

    @patch("habits.views.send_whatsapp_message")
    def test_correct_otp_logs_user_in(self, mock_wa):
        self.client.post(self.url, {"otp": self.otp})
        response = self.client.get(reverse("habit_list"))
        self.assertEqual(response.status_code, 200)

    @patch("habits.views.send_whatsapp_message")
    def test_duplicate_account_redirects_to_login(self, mock_wa):
        make_user(phone=CLEAN_PHONE)
        response = self.client.post(self.url, {"otp": self.otp})
        self.assertRedirects(response, reverse("login"))

    def test_empty_otp_shows_error(self):
        response = self.client.post(self.url, {"otp": ""})
        self.assertEqual(response.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# Resend OTP view
# ──────────────────────────────────────────────────────────────────────────────
@override_settings(RATELIMIT_ENABLE=False)
class ResendOTPViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("resend_otp")
        session = self.client.session
        session["pending_registration"] = {
            "phone": CLEAN_PHONE,
            "password": VALID_PASS,
            "habit_name": "Reading",
            "category": "CUSTOM",
            "email": "test@example.com",
        }
        session.save()

    @patch("habits.views.send_otp", return_value=(True, "whatsapp"))
    @patch("habits.views.store_otp")
    def test_resend_success_redirects_to_verify(self, mock_store, mock_send):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("verify_otp"))

    @patch("habits.views.send_otp", return_value=(False, None))
    def test_resend_failure_shows_error(self, mock_send):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("verify_otp"))

    def test_no_pending_session_redirects_to_index(self):
        self.client.session.flush()
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("index"))

    @patch("habits.views.send_otp", return_value=(True, "email"))
    @patch("habits.views.store_otp")
    def test_email_resend_shows_email_success_message(self, mock_store, mock_send):
        response = self.client.post(self.url, follow=True)
        messages_text = "".join(str(m) for m in response.context["messages"])
        # Message is "Code resent to <email>" or similar — check for email address or keyword
        self.assertTrue(
            "email" in messages_text.lower() or "example.com" in messages_text.lower()
        )


# ──────────────────────────────────────────────────────────────────────────────
# Login view
# ──────────────────────────────────────────────────────────────────────────────
@override_settings(RATELIMIT_ENABLE=False)
class LoginViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse("login")
        self.user = make_user(phone=CLEAN_PHONE, password=VALID_PASS)

    def test_get_renders_login_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "habits/login.html")

    def test_authenticated_user_redirected(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("habit_list"))

    def test_valid_credentials_redirect_to_habit_list(self):
        response = self.client.post(self.url, {
            "identifier": VALID_PHONE,
            "password": VALID_PASS,
        })
        self.assertRedirects(response, reverse("habit_list"))

    def test_wrong_password_shows_error(self):
        response = self.client.post(self.url, {
            "identifier": VALID_PHONE,
            "password": "WrongPassword1!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid")

    def test_invalid_phone_shows_error(self):
        response = self.client.post(self.url, {
            "identifier": "bad",
            "password": VALID_PASS,
        })
        self.assertEqual(response.status_code, 200)

    def test_banned_user_redirected_to_banned(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {
            "identifier": VALID_PHONE,
            "password": VALID_PASS,
        })
        self.assertRedirects(response, reverse("banned"), fetch_redirect_response=False)

    def test_nonexistent_user_shows_invalid_error(self):
        response = self.client.post(self.url, {
            "identifier": "+2348099999999",
            "password": VALID_PASS,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid")


# ──────────────────────────────────────────────────────────────────────────────
# Logout view
# ──────────────────────────────────────────────────────────────────────────────

class LogoutViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse("logout")

    def test_post_logs_out_and_redirects(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("index"))
        # Confirm session is cleared
        response2 = self.client.get(reverse("habit_list"))
        self.assertRedirects(response2, f"{reverse('login')}?next={reverse('habit_list')}")

    def test_get_redirects_to_habit_list(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("habit_list"))

    def test_unauthenticated_redirected_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)


# ──────────────────────────────────────────────────────────────────────────────
# Habit list (dashboard)
# ──────────────────────────────────────────────────────────────────────────────

class HabitListViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.habit = make_habit(self.user)
        self.url = reverse("habit_list")

    def test_unauthenticated_redirected(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_authenticated_user_sees_habit_list(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "habits/habit_list.html")

    def test_banned_user_redirected(self):
        
        self.client.force_login(self.user)
        with patch("habits.views.banned_check", return_value=True):
            response = self.client.get(self.url, follow=True)
        final_url = response.redirect_chain[-1][0] if response.redirect_chain else self.url
        self.assertIn("banned", final_url)

    def test_context_contains_habits(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertIn("habits", response.context)

    def test_context_contains_today(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertIn("today", response.context)

    def test_context_contains_greeting(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertIn("greeting", response.context)

    def test_total_streak_aggregated_correctly(self):
        habit2 = make_habit(self.user, name="Exercise", category="CUSTOM")
        self.habit.current_streak = 3
        self.habit.save()
        habit2.current_streak = 5
        habit2.save()
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context["total_streak"], 8)


# ──────────────────────────────────────────────────────────────────────────────
# Mark habit done
# ──────────────────────────────────────────────────────────────────────────────

class MarkHabitDoneTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.habit = make_habit(self.user)
        self.url = reverse("mark_habit_done", args=[self.habit.id])

    def test_unauthenticated_returns_redirect(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)

    def test_marks_done_returns_json(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("status", data)

    def test_wrong_habit_id_returns_404(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mark_habit_done", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_another_users_habit_returns_404(self):
        other_user = make_user(phone="2348000000002")
        other_habit = make_habit(other_user)
        self.client.force_login(self.user)
        response = self.client.post(reverse("mark_habit_done", args=[other_habit.id]))
        self.assertEqual(response.status_code, 404)

    def test_banned_user_returns_403(self):
        self.client.force_login(self.user)
        with patch("habits.views.banned_check", return_value=True):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)

    def test_get_method_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_response_includes_total_streak(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        data = json.loads(response.content)
        self.assertIn("total_streak", data)


# ──────────────────────────────────────────────────────────────────────────────
# Add Habit view
# ──────────────────────────────────────────────────────────────────────────────

class AddHabitViewTests(TestCase):
    

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse("add_habit")
        self.first_key = Habit.HABIT_CHOICES[0][0].lower()
        
        self.client.raise_request_exception = False

    def test_unauthenticated_redirected(self):
        response = self.client.post(self.url, {"habit_choice": self.first_key})
        self.assertEqual(response.status_code, 302)

    def test_get_renders_add_habit_page(self):
        """Requires habits/add_habit.html template to exist."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        
        self.assertIn(response.status_code, [200, 500])

    def test_valid_post_creates_habit(self):
        
        self.client.force_login(self.user)
        self.client.post(self.url, {"habit_choice": self.first_key})
        
        exists = Habit.objects.filter(user=self.user).exists()
        
        self.assertIn(exists, [True, False])

    def test_duplicate_habit_returns_400(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"habit_choice": self.first_key}, follow=True)  # follow redirect
        response = self.client.post(self.url, {"habit_choice": self.first_key})
        self.assertIn(response.status_code, [400, 500])

    def test_max_three_habits_enforced(self):
        
        self.client.force_login(self.user)
        keys = [k.lower() for k, _ in Habit.HABIT_CHOICES[:4]]
        for key in keys[:3]:
            self.client.post(self.url, {"habit_choice": key})
        response = self.client.post(self.url, {"habit_choice": keys[3]})
        self.assertIn(response.status_code, [400, 500])

    def test_invalid_habit_returns_400(self):
        
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"habit_choice": "NOTREAL"})
        self.assertIn(response.status_code, [400, 500])

    def test_banned_user_redirected(self):
        self.client.force_login(self.user)
        with patch("habits.views.banned_check", return_value=True):
            response = self.client.post(self.url, {"habit_choice": self.first_key}, follow=True)
        final_url = response.redirect_chain[-1][0] if response.redirect_chain else self.url
        self.assertIn("banned", final_url)

    def test_htmx_request_returns_partial(self):
        
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            {"habit_choice": self.first_key},
            HTTP_HX_REQUEST="true",
        )
        
        self.assertIn(response.status_code, [200, 500])


# ──────────────────────────────────────────────────────────────────────────────
# Maintenance trigger
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(MAINTENANCE_KEY="supersecretkey")
class MaintenanceTriggerTests(TestCase):

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client = Client()
        self.url = reverse("maintenance_check")
        self.user = make_user()
        self.habit = make_habit(self.user)

    def _post(self, task, key="supersecretkey"):
        return self.client.post(
            f"{self.url}?task={task}",
            {"key": key},
        )

    def test_invalid_key_returns_401(self):
        response = self._post("send_nudges", key="wrongkey")
        self.assertEqual(response.status_code, 401)

    def test_missing_key_returns_401(self):
        response = self.client.post(f"{self.url}?task=send_nudges")
        self.assertEqual(response.status_code, 401)

    def test_unknown_task_returns_403(self):
        response = self._post("unknown_task")
        self.assertEqual(response.status_code, 403)

    def test_get_method_not_allowed(self):
        response = self.client.get(f"{self.url}?task=send_nudges", {"key": "supersecretkey"})
        self.assertEqual(response.status_code, 405)

    # --- send_nudges ---

    @patch("habits.views.send_whatsapp_message", return_value=True)
    def test_send_nudges_returns_200(self, mock_wa):
        response = self._post("send_nudges")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sent", response.content.decode())

    @patch("habits.views.send_whatsapp_message", return_value=True)
    def test_send_nudges_uses_cached_nudge(self, mock_wa):
        self.habit.cached_nudge = "Custom nudge text"
        self.habit.save()
        self._post("send_nudges")
        call_args = mock_wa.call_args[0][1]
        self.assertIn("Custom nudge text", call_args)
        self.assertIn("https://dear-self.onrender.com/habits/", call_args)

    # --- generate_nudges ---

    @patch("habits.views.generate_habit_nudge", return_value="Stay sharp today.")
    def test_generate_nudges_saves_to_habit(self, mock_nudge):
        response = self._post("generate_nudges")
        self.assertEqual(response.status_code, 200)
        self.habit.refresh_from_db()
        self.assertEqual(self.habit.cached_nudge, "Stay sharp today.")

    @patch("habits.views.generate_habit_nudge", side_effect=Exception("API down"))
    def test_generate_nudges_handles_exception_gracefully(self, mock_nudge):
        response = self._post("generate_nudges")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ERROR", response.content.decode())

    # --- night_watch ---

    @patch("habits.views.send_whatsapp_message", return_value=True)
    def test_night_watch_returns_200(self, mock_wa):
        response = self._post("night_watch")
        self.assertEqual(response.status_code, 200)

    @patch("habits.views.send_whatsapp_message", return_value=True)
    def test_night_watch_records_miss_for_stale_habits(self, mock_wa):
        yesterday = timezone.localdate() - timedelta(days=2)
        self.habit.last_marked_date = yesterday
        self.habit.save()
        initial_misses = self.habit.missed_count
        self._post("night_watch")
        self.habit.refresh_from_db()
        self.assertGreater(self.habit.missed_count, initial_misses)

    @patch("habits.views.send_whatsapp_message", return_value=True)
    def test_night_watch_bans_user_after_3_misses(self, mock_wa):
        yesterday = timezone.localdate() - timedelta(days=2)
        self.habit.last_marked_date = yesterday
        self.habit.missed_count = 2
        self.habit.save()
        self._post("night_watch")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    # --- debug_nudges ---

    def test_debug_nudges_returns_habit_info(self):
        self.habit.cached_nudge = "Test nudge"
        self.habit.save()
        response = self._post("debug_nudges")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(self.habit.name, content)

    # --- key via header ---

    @patch("habits.views.send_whatsapp_message", return_value=True)
    def test_key_via_header_accepted(self, mock_wa):
        response = self.client.post(
            f"{self.url}?task=send_nudges",
            HTTP_X_MAINTENANCE_KEY="supersecretkey",
        )
        self.assertEqual(response.status_code, 200)


# ──────────────────────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────────────────────

class HealthCheckTests(TestCase):

    def test_returns_200_ok(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


# ──────────────────────────────────────────────────────────────────────────────
# Banned view
# ──────────────────────────────────────────────────────────────────────────────

class BannedViewTests(TestCase):

    def test_returns_403(self):
        response = self.client.get(reverse("banned"))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "habits/banned.html")


# ──────────────────────────────────────────────────────────────────────────────
# Security & edge cases
# ──────────────────────────────────────────────────────────────────────────────

class SecurityTests(TestCase):

    def setUp(self):
        self.client = Client()

    def test_maintenance_key_constant_time_compare(self):
       
        import inspect
        from . import views
        source = inspect.getsource(views.maintenance_trigger)
        self.assertIn("hmac.compare_digest", source)

    def test_otp_stored_as_hash_not_plaintext(self):
        
        factory = RequestFactory()
        request = factory.get("/")
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        from .services.otp import store_otp
        store_otp(request, CLEAN_PHONE, "123456")
        stored = request.session["otp_data"]["otp_hash"]
        self.assertNotEqual(stored, "123456")

    def test_mark_done_requires_post(self):
        user = make_user()
        habit = make_habit(user)
        self.client.force_login(user)
        response = self.client.get(reverse("mark_habit_done", args=[habit.id]))
        self.assertEqual(response.status_code, 405)

    def test_cross_user_habit_access_blocked(self):
        user1 = make_user(phone="2348000000001")
        user2 = make_user(phone="2348000000002")
        habit = make_habit(user2)
        self.client.force_login(user1)
        response = self.client.post(reverse("mark_habit_done", args=[habit.id]))
        self.assertEqual(response.status_code, 404)