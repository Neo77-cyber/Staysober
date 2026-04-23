import requests
import logging
from django.conf import settings
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = logging.getLogger(__name__)


GEMINI_MODELS = [
    "gemini-3.1-flash-lite-preview",  
    "gemini-2.5-flash",               
    "gemini-2.0-flash",              
]

def _get_gemini_url(model, api_key):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

def is_429_error(exception):
    return isinstance(exception, requests.exceptions.HTTPError) and \
           exception.response.status_code == 429

@retry(
    retry=retry_if_exception(is_429_error),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True
)
def _call_gemini_api(url, payload):
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()

def generate_habit_nudge(habit_name, streak, missed_count):
    """
    Analyzes the habit status and generates a Lagos-style 
    tough-love message using Gemini models.
    """
    api_key = settings.GEMINI_API_KEY
    
    
    prompt = (
        f"Context: I am building a 'Stay Sober' app in Lagos. "
        f"User is tracking '{habit_name}'. Current stats: {streak}-day streak, {missed_count}/3 misses used. "
        "Task: Write 1 short, punchy sentence of motivation or warning. "
        "Tone: Lagos street smarts / Tough love mentor. Use a mix of English and Pidgin. "
        "Rules: No emojis. Max 20 words. If misses are 2, sound very stern."
    )

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for model in GEMINI_MODELS:
        try:
            url = _get_gemini_url(model, api_key)
            data = _call_gemini_api(url, payload)
            return data['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            
            logger.error(f"Gemini {model} failed: {str(e)}")
            
            
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Google API Error Body: {e.response.text}")
            
            continue 

    return "No allow your fire go out. Stay focused."