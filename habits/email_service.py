from django.core.mail import send_mail
from django.conf import settings
import logging
 
logger = logging.getLogger(__name__)
 
 
def send_otp_email(email: str, otp: str, expiry_minutes: int) -> bool:
    """Send OTP via email as fallback when WhatsApp quota is exceeded."""
    try:
        send_mail(
            subject="Your DearSelf verification code",
            message=(
                f"Your verification code is: {otp}\n\n"
                f"It expires in {expiry_minutes} minutes.\n"
                f"Do not share this with anyone.\n\n"
                f"— DearSelf"
            ),
            html_message=f"""
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
            """,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error("Email OTP send failed to %s: %s", email[:4] + "****", e)
        return False
