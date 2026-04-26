import random
import logging
from django.utils import timezone
from .whatsapp import send_whatsapp_message
import secrets 

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 15
OTP_MAX_ATTEMPTS = 5


def generate_otp():
    return str(secrets.randbelow(900000) + 100000)


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


import hashlib


def store_otp(request, phone_number: str, otp: str):
    hashed = hashlib.sha256(otp.encode()).hexdigest()
    request.session['otp_data'] = {
        'otp_hash': hashed,
        'phone': phone_number,
        'expires_at': (timezone.now() + timezone.timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat(),
        'attempts': 0,
    }


def verify_otp(request, phone_number: str, submitted_otp: str) -> tuple[bool, str]:
    submitted_hash = hashlib.sha256(submitted_otp.strip().encode()).hexdigest()
    data = request.session.get('otp_data')

    if not data:
        return False, "No OTP found. Please start registration again."

    if data['phone'] != phone_number:
        return False, "Phone number mismatch. Please start again."

    if timezone.now() > timezone.datetime.fromisoformat(data['expires_at']).replace(tzinfo=timezone.utc):
        clear_otp(request)
        return False, "OTP has expired. Please request a new one."

    if data['attempts'] >= OTP_MAX_ATTEMPTS:
        clear_otp(request)
        return False, "Too many failed attempts. Please start again."

    if data['otp_hash'] != submitted_hash:
        data['attempts'] += 1
        request.session['otp_data'] = data
        request.session.modified = True
        remaining = OTP_MAX_ATTEMPTS - data['attempts']
        return False, f"Wrong code. {remaining} attempt(s) left."

    clear_otp(request)
    return True, "ok"


def clear_otp(request):
    request.session.pop('otp_data', None)