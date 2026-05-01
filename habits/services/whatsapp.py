from whatsapp_api_client_python import API
from django.conf import settings
from django.core.cache import cache
import logging
from .helpers import mask_phone
 
logger = logging.getLogger(__name__)
 
WA_QUOTA_EXCEEDED_KEY = "green_api_quota_exceeded"
WA_QUOTA_COOLDOWN = 60 * 60 * 6  
 
green_api = None
 
def get_green_api():
    global green_api
    if green_api is None:
        green_api = API.GreenAPI(settings.GREEN_API_ID, settings.GREEN_API_TOKEN)
    return green_api
 
 
def is_whatsapp_quota_exceeded() -> bool:
    return cache.get(WA_QUOTA_EXCEEDED_KEY) is not None
 
 
def mark_whatsapp_quota_exceeded():
    cache.set(WA_QUOTA_EXCEEDED_KEY, True, timeout=WA_QUOTA_COOLDOWN)
    logger.warning("Green API quota exhausted — falling back to email for %dh.", WA_QUOTA_COOLDOWN // 3600)
 
 
def send_whatsapp_message(phone_number: str, message: str) -> bool:
    if is_whatsapp_quota_exceeded():
        logger.info("WhatsApp quota cooldown active — skipping send.")
        return False
 
    chat_id = f"{phone_number}@c.us"
    try:
        api = get_green_api()
        response = api.sending.sendMessage(chat_id, message)
        if response.code == 200:
            return True
 
        
        if response.code in (429, 403) or (
            hasattr(response, 'data') and
            'quota' in str(response.data).lower()
        ):
            mark_whatsapp_quota_exceeded()
 
        logger.error("Green-API Error %s: %s", response.code, getattr(response, 'data', ''))
        return False
 
    except Exception as e:
        error_str = str(e).lower()
        if 'quota' in error_str or 'limit' in error_str or 'exhausted' in error_str:
            mark_whatsapp_quota_exceeded()
        logger.error("Failed to send WA message to %s****: %s", mask_phone(phone_number)[:4], e)
        return False
 
 
def send_otp_whatsapp(phone_number: str, otp: str, expiry_minutes: int) -> bool:
   
    if is_whatsapp_quota_exceeded():
        return False
 
    message = (
        f"*Your DearSelf verification code is: {otp}*\n\n"
        f"It expires in {expiry_minutes} minutes. Do not share this with anyone."
    )
    return send_whatsapp_message(phone_number, message)
