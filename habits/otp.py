import random
import logging
from django.utils.timezone import now as tz_now
import datetime
from .whatsapp import send_whatsapp_message

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 15
OTP_MAX_ATTEMPTS = 5


def generate_otp():
    return str(random.randint(100000, 999999))


def send_otp(phone_number: str, otp: str) -> bool:
    message = (
        f"*Your verification code is: {otp}*\n\n"
        f"It expires in {OTP_EXPIRY_MINUTES} minutes. Do not share this with anyone."
    )
    try:
        send_whatsapp_message(phone_number, message)
        return True
    except Exception as e:
        logger.error(f"OTP send failed for {phone_number}: {e}")
        return False


def store_otp(request, phone_number: str, otp: str):
    request.session['otp_data'] = {
        'otp': otp,
        'phone': phone_number,
        'expires_at': expires_at.isoformat(),
        'attempts': 0,
    }


def verify_otp(request, phone_number: str, submitted_otp: str) -> tuple[bool, str]:
    data = request.session.get('otp_data')

    if not data:
        return False, "No OTP found. Please start registration again."

    if data['phone'] != phone_number:
        return False, "Phone number mismatch. Please start again."

    if tz_now() > datetime.datetime.fromisoformat(data['expires_at']):
        clear_otp(request)
        return False, "OTP has expired. Please request a new one."

    if data['attempts'] >= OTP_MAX_ATTEMPTS:
        clear_otp(request)
        return False, "Too many failed attempts. Please start again."

    if data['otp'] != submitted_otp.strip():
        data['attempts'] += 1
        request.session['otp_data'] = data
        request.session.modified = True
        remaining = OTP_MAX_ATTEMPTS - data['attempts']
        return False, f"Wrong code. {remaining} attempt(s) left."

    clear_otp(request)
    return True, "ok"


def clear_otp(request):
    request.session.pop('otp_data', None)