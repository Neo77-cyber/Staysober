import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_otp_email(email: str, otp: str, expiry_minutes: int) -> bool:
    """
    Send OTP email using Resend API
    """
    try:
        RESEND_API_KEY = settings.RESEND_API_KEY

        subject = "Your DearSelf verification code"

        html_message = f"""
            <div style="font-family: sans-serif; max-width: 400px; margin: 0 auto; padding: 2rem;">
                <h2 style="font-size: 1.5rem; font-weight: 800; margin-bottom: 0.5rem;">DearSelf</h2>
                <p style="color: #6b7280; margin-bottom: 2rem;">Your verification code</p>
                <div style="background: #f3f4f6; border-radius: 12px; padding: 2rem; text-align: center; margin-bottom: 2rem;">
                    <span style="font-size: 2.5rem; font-weight: 800; letter-spacing: 0.5rem;">{otp}</span>
                </div>
                <p style="color: #6b7280; font-size: 0.875rem;">
                    This code expires in {expiry_minutes} minutes.<br>
                    Do not share this with anyone.
                </p>
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 2rem 0;">
                <p style="color: #9ca3af; font-size: 0.75rem;">
                    DearSelf is in early access. WhatsApp reminders are coming soon.
                </p>
            </div>
        """

        plain_message = f"""Your verification code is: {otp}

It expires in {expiry_minutes} minutes.
Do not share this with anyone.

— DearSelf

DearSelf is in early access. WhatsApp reminders are coming soon."""

        email_data = {
            "from": "DearSelf <support@retechloans.com>",
            "to": [email],
            "subject": subject,
            "html": html_message,
            "text": plain_message,
            "reply_to": "support@retechloans.com",
        }

        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=email_data,
            timeout=10,
        )

        if response.status_code == 200:
            logger.info(f"OTP email sent to {email[:4]}****")
            return True
        else:
            logger.error(f"Email API error for {email[:4]}****: {response.text}")
            return False

    except Exception as e:
        logger.error("Email OTP send failed to %s****: %s", email[:4], str(e))
        return False
