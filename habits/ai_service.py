import requests
import logging
from django.conf import settings
from django.core.cache import cache
from typing import Optional

logger = logging.getLogger(__name__)


GEMINI_MODELS = [
    "gemini-3.1-flash-lite",   
    "gemini-2.5-flash",        
    "gemini-2.0-flash",        
]


QUOTA_COOLDOWN_SECONDS = 65

FALLBACK_NUDGES = [
    "No allow your fire go out. Stay focused.",
    "You don start, no go back now. Finish what you started.",
    "Every day you hold on, you dey win. Keep going.",
    "Your future self go thank you. Do it for am.",
    "The goal no go chase itself. You must move.",
]


def _get_gemini_url(model: str, api_key: str) -> str:
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models"
        f"/{model}:generateContent?key={api_key}"
    )


def _model_cache_key(model: str) -> str:
    """Cache key for per-model quota exceeded flag."""
    return f"gemini_quota_{model.replace('-', '_')}"


def _is_model_exhausted(model: str) -> bool:
    return cache.get(_model_cache_key(model)) is not None


def _mark_model_exhausted(model: str):
    cache.set(_model_cache_key(model), True, timeout=QUOTA_COOLDOWN_SECONDS)
    logger.warning("Gemini %s marked exhausted for %ds.", model, QUOTA_COOLDOWN_SECONDS)


def _call_gemini(url: str, payload: dict) -> dict:
    """Raw API call. Raises on non-2xx. No retry logic — caller handles fallback."""
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def _extract_text(data: dict) -> Optional[str]:
    """Safely pull text out of Gemini response structure."""
    try:
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError, TypeError):
        return None


def _get_fallback(missed_count: int) -> str:
    return FALLBACK_NUDGES[missed_count % len(FALLBACK_NUDGES)]


def generate_habit_nudge(habit_name: str, streak: int, missed_count: int) -> str:
    
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — using fallback.")
        return _get_fallback(missed_count)

    
    available_models = [m for m in GEMINI_MODELS if not _is_model_exhausted(m)]
    if not available_models:
        logger.info("All Gemini models currently quota-exhausted — using fallback.")
        return _get_fallback(missed_count)

    prompt = (
        f"Context: I am building a 'Stay Sober' app in Lagos. "
        f"User is tracking '{habit_name}'. "
        f"Current stats: {streak}-day streak, {missed_count}/3 misses used. "
        "Task: Write 1 short, punchy sentence of motivation or warning. "
        "Tone: Lagos street smarts / Tough love mentor. Mix English and Pidgin naturally. "
        "Rules: No emojis. Max 20 words. "
        "If misses are 2, be very stern — they are one miss from being banned."
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for model in available_models:
        url = _get_gemini_url(model, api_key)
        try:
            data = _call_gemini(url, payload)
            text = _extract_text(data)
            if text:
                logger.info("Nudge generated via %s.", model)
                return text
            
            logger.warning("Gemini %s unexpected response structure: %s", model, data)
            continue

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            body = e.response.text[:300] if e.response is not None else ""

            if status == 429:
                
                logger.error("Gemini %s quota exceeded (429) — trying next model.", model)
                _mark_model_exhausted(model)
                continue  

            elif status == 403:
                
                logger.critical(
                    "Gemini 403 PERMISSION_DENIED on %s. "
                    "API key may be leaked or revoked — rotate it immediately. Body: %s",
                    model, body
                )
                break

            elif status == 404:
                
                logger.warning("Gemini model %s not found (404) — skipping.", model)
                continue

            else:
                logger.error("Gemini %s HTTP %s: %s", model, status, body)
                continue

        except requests.exceptions.Timeout:
            logger.error("Gemini %s timed out.", model)
            continue

        except requests.exceptions.ConnectionError as e:
            logger.error("Gemini %s connection error: %s", model, e)
            continue

        except Exception as e:
            logger.error("Gemini %s unexpected error: %s", model, e, exc_info=True)
            continue

    fallback = _get_fallback(missed_count)
    logger.warning("All Gemini models failed — using fallback: %s", fallback)
    return fallback