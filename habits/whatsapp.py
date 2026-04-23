from whatsapp_api_client_python import API
from django.conf import settings
import logging

logger = logging.getLogger(__name__)
green_api = API.GreenAPI(settings.GREEN_API_ID, settings.GREEN_API_TOKEN)

def validate_and_send_welcome(phone_number, user_name):
    chat_id = f"{phone_number}@c.us"
    
    try:
        
        status = green_api.account.getStateInstance()
        instance_state = status.data.get('stateInstance')

        if instance_state == 'notAuthorized':
            return False, "system_not_authorized"
        elif instance_state == 'starting':
            return False, "system_starting"
        elif instance_state != 'authorized':
            return False, "system_offline"

        
        check = green_api.serviceMethods.checkWhatsapp(phone_number)
        
        if check.code == 200 and check.data.get('existsWhatsapp') is True:
            message = (
                f"Welcome {user_name}, I will be your chatbot partner that helps you keep your streak. "
                f"I will remind you 3 times a day. If you lose your streak for 3 days, you are out. Be warned."
            )
            response = green_api.sending.sendMessage(chat_id, message)
            return True, "success"
        else:
            return False, "invalid_number"
            
    except Exception as e:
        logger.error(f"Green-API Exception: {e}")
        return False, "api_error"


def send_whatsapp_message(phone_number, message):
    
    chat_id = f"{phone_number}@c.us"
    try:
        response = green_api.sending.sendMessage(chat_id, message)
        if response.code == 200:
            return True
        else:
            logger.error(f"Green-API Error Code {response.code}: {response.data}")
            return False
    except Exception as e:
        logger.error(f"Failed to send WA message to {phone_number}: {e}")
        return False