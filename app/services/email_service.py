"""
Email service — sends transactional emails via SMTP.
Fails silently (logs a warning) if SMTP is not configured.
"""
import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.saas_layer.core.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to: str, subject: str, html_body: str, text_body: str = "") -> None:
    """Synchronous SMTP send — run via run_in_executor to stay non-blocking."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.FROM_EMAIL
    msg["To"] = to

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.FROM_EMAIL, to, msg.as_string())


async def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """
    Send an email asynchronously.
    Returns True on success, False if SMTP is not configured or on error.
    """
    if not settings.email_enabled:
        logger.warning(
            "SMTP not configured — email NOT sent to %s | Subject: %s", to, subject
        )
        return False
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_sync, to, subject, html_body, text_body)
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------

async def send_verification_email(to: str, code: str) -> bool:
    # Always print to server console so devs can verify even without SMTP
    logger.warning(">>> VERIFICATION CODE for %s: %s <<<", to, code)
    subject = "Verify your VideoSplit account"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
      <h2 style="color:#667eea">VideoSplit — Email Verification</h2>
      <p>Hi there,</p>
      <p>Your verification code is:</p>
      <div style="font-size:2.5em;font-weight:700;letter-spacing:.2em;color:#111;
                  background:#f3f4f6;border-radius:10px;padding:20px;text-align:center;
                  margin:20px 0">{code}</div>
      <p style="color:#6b7280">This code expires in <strong>15 minutes</strong>.</p>
      <p style="color:#6b7280">If you didn't create an account, you can safely ignore this email.</p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
      <p style="color:#9ca3af;font-size:.85em">— VideoSplit Team</p>
    </div>
    """
    text = f"Your VideoSplit verification code is: {code}\nExpires in 15 minutes."
    return await send_email(to, subject, html, text)


async def send_password_reset_email(to: str, reset_url: str) -> bool:
    subject = "Reset your VideoSplit password"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
      <h2 style="color:#667eea">VideoSplit — Password Reset</h2>
      <p>Hi,</p>
      <p>Click the button below to reset your password:</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{reset_url}" style="background:#667eea;color:#fff;text-decoration:none;
           padding:14px 28px;border-radius:8px;font-weight:600;display:inline-block">
          Reset Password
        </a>
      </div>
      <p style="color:#6b7280">This link expires in <strong>1 hour</strong>.</p>
      <p style="color:#6b7280">If you didn't request a password reset, ignore this email.</p>
      <p style="color:#9ca3af;font-size:.85em;word-break:break-all">
        Or copy this link: {reset_url}
      </p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
      <p style="color:#9ca3af;font-size:.85em">— VideoSplit Team</p>
    </div>
    """
    text = f"Reset your VideoSplit password: {reset_url}\nLink expires in 1 hour."
    return await send_email(to, subject, html, text)


async def send_password_changed_email(to: str) -> bool:
    subject = "Your VideoSplit password was changed"
    html = """
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
      <h2 style="color:#667eea">VideoSplit — Password Changed</h2>
      <p>Your password was successfully changed.</p>
      <p style="color:#6b7280">If you didn't do this, please contact us immediately
         or reset your password.</p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
      <p style="color:#9ca3af;font-size:.85em">— VideoSplit Team</p>
    </div>
    """
    return await send_email(to, subject, html)


async def send_alert_email(error_type: str, detail: str, stack_trace: str = "") -> bool:
    """Send an internal alert to the configured ALERT_EMAIL."""
    if not settings.ALERT_EMAIL:
        return False
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"[ALERT] VideoSplit — {error_type}"
    html = f"""
    <div style="font-family:monospace;max-width:640px;margin:0 auto;padding:32px">
      <h2 style="color:#ef4444">[ALERT] {error_type}</h2>
      <p><strong>Time:</strong> {ts}</p>
      <p><strong>Detail:</strong> {detail}</p>
      {"<pre style='background:#f3f4f6;padding:16px;border-radius:8px;white-space:pre-wrap'>" + stack_trace + "</pre>" if stack_trace else ""}
    </div>
    """
    return await send_email(settings.ALERT_EMAIL, subject, html)
