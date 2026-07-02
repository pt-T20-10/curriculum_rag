import logging
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.services.runtime_config import get_runtime_config

logger = logging.getLogger(__name__)


def _build_otp_html(otp_code: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden">
        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,#667eea,#764ba2);padding:32px 40px;text-align:center">
          <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700">
            Hệ Thống Tạo Giáo Trình AI
          </h1>
          <p style="margin:6px 0 0;color:rgba(255,255,255,.85);font-size:14px">
            Đặt lại mật khẩu
          </p>
        </td></tr>
        <!-- Body -->
        <tr><td style="padding:36px 40px">
          <p style="margin:0 0 16px;color:#333;font-size:15px">Xin chào,</p>
          <p style="margin:0 0 24px;color:#555;font-size:14px;line-height:1.6">
            Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản của bạn.
            Sử dụng mã xác nhận bên dưới để tiếp tục. Mã có hiệu lực trong
            <strong>15 phút</strong>.
          </p>
          <!-- OTP box -->
          <div style="text-align:center;margin:28px 0">
            <div style="display:inline-block;background:#f0f0ff;border:2px dashed #667eea;
                        border-radius:10px;padding:18px 36px">
              <span style="font-size:36px;font-weight:800;letter-spacing:10px;color:#4c51bf">
                {otp_code}
              </span>
            </div>
          </div>
          <p style="margin:0 0 8px;color:#888;font-size:13px;text-align:center">
            Nếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email này.
          </p>
          <p style="margin:0;color:#f56565;font-size:12px;text-align:center">
            Không chia sẻ mã này với bất kỳ ai.
          </p>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background:#f9f9f9;padding:20px 40px;text-align:center;
                        border-top:1px solid #eee">
          <p style="margin:0;color:#aaa;font-size:12px">
            © 2026 Hệ Thống Tạo Giáo Trình AI. Tất cả quyền được bảo lưu.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _build_email_verification_html(otp_code: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden">
        <tr><td style="background:linear-gradient(135deg,#2563eb,#7c3aed);padding:32px 40px;text-align:center">
          <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700">
            Hệ Thống Tạo Giáo Trình AI
          </h1>
          <p style="margin:6px 0 0;color:rgba(255,255,255,.85);font-size:14px">
            Xác nhận email đăng ký
          </p>
        </td></tr>
        <tr><td style="padding:36px 40px">
          <p style="margin:0 0 16px;color:#333;font-size:15px">Xin chào,</p>
          <p style="margin:0 0 24px;color:#555;font-size:14px;line-height:1.6">
            Cảm ơn bạn đã đăng ký tài khoản. Nhập mã xác nhận bên dưới để hoàn tất
            đăng ký và bắt đầu sử dụng hệ thống. Mã có hiệu lực trong
            <strong>15 phút</strong>.
          </p>
          <div style="text-align:center;margin:28px 0">
            <div style="display:inline-block;background:#eef2ff;border:2px dashed #4f46e5;
                        border-radius:10px;padding:18px 36px">
              <span style="font-size:36px;font-weight:800;letter-spacing:10px;color:#3730a3">
                {otp_code}
              </span>
            </div>
          </div>
          <p style="margin:0 0 8px;color:#888;font-size:13px;text-align:center">
            Nếu bạn không đăng ký tài khoản này, hãy bỏ qua email này.
          </p>
          <p style="margin:0;color:#f56565;font-size:12px;text-align:center">
            Không chia sẻ mã này với bất kỳ ai.
          </p>
        </td></tr>
        <tr><td style="background:#f9f9f9;padding:20px 40px;text-align:center;
                        border-top:1px solid #eee">
          <p style="margin:0;color:#aaa;font-size:12px">
            © 2026 Hệ Thống Tạo Giáo Trình AI. Tất cả quyền được bảo lưu.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


async def send_email_verification_email(to_email: str, otp_code: str) -> None:
    """Send account email verification OTP via SMTP."""
    smtp_user = str(get_runtime_config("SMTP_USER", required=False) or "")
    smtp_password = str(get_runtime_config("SMTP_PASSWORD", required=False) or "")
    if not smtp_user or not smtp_password:
        logger.warning("SMTP not configured — skipping email verification send (OTP: %s)", otp_code)
        return

    smtp_host = str(get_runtime_config("SMTP_HOST", required=False) or "smtp.gmail.com")
    smtp_port = int(get_runtime_config("SMTP_PORT", required=False) or 587)
    email_from = str(get_runtime_config("EMAIL_FROM", required=False) or smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Mã xác nhận email đăng ký"
    msg["From"] = email_from
    msg["To"] = to_email

    msg.attach(MIMEText(_build_email_verification_html(otp_code), "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
        )
        logger.info("Email verification sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send email verification to %s: %s", to_email, exc)
        raise


async def send_password_reset_email(to_email: str, otp_code: str) -> None:
    """Send OTP reset code to `to_email` via SMTP (TLS/STARTTLS on port 587)."""
    smtp_user = str(get_runtime_config("SMTP_USER", required=False) or "")
    smtp_password = str(get_runtime_config("SMTP_PASSWORD", required=False) or "")
    if not smtp_user or not smtp_password:
        logger.warning("SMTP not configured — skipping email send (OTP: %s)", otp_code)
        return

    smtp_host = str(get_runtime_config("SMTP_HOST", required=False) or "smtp.gmail.com")
    smtp_port = int(get_runtime_config("SMTP_PORT", required=False) or 587)
    email_from = str(get_runtime_config("EMAIL_FROM", required=False) or smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Mã xác nhận đặt lại mật khẩu"
    msg["From"] = email_from
    msg["To"] = to_email

    msg.attach(MIMEText(_build_otp_html(otp_code), "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
        )
        logger.info("Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send reset email to %s: %s", to_email, exc)
        raise


async def send_support_request_email(
    to_email: str,
    sender_name: str,
    sender_email: str,
    subject: str,
    description: str,
    ui_language: str,
) -> bool:
    """Send a support request to a server-selected recipient via SMTP."""
    smtp_user = str(get_runtime_config("SMTP_USER", required=False) or "")
    smtp_password = str(get_runtime_config("SMTP_PASSWORD", required=False) or "")
    if not smtp_user or not smtp_password:
        logger.error("SMTP is not configured; support request email was not sent")
        return False

    smtp_host = str(get_runtime_config("SMTP_HOST", required=False) or "smtp.gmail.com")
    smtp_port = int(get_runtime_config("SMTP_PORT", required=False) or 587)
    email_from = str(get_runtime_config("EMAIL_FROM", required=False) or smtp_user)

    safe_name = escape(sender_name)
    safe_email = escape(sender_email)
    safe_subject = escape(subject)
    safe_description = escape(description).replace("\n", "<br>")
    language_label = "English" if ui_language == "en" else "Tiếng Việt"

    plain_body = (
        "New support request\n\n"
        f"Name: {sender_name}\n"
        f"Email: {sender_email}\n"
        f"UI language: {language_label}\n"
        f"Subject: {subject}\n\n"
        f"Issue description:\n{description}\n"
    )
    html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:Arial,sans-serif;color:#1f2937">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
             style="max-width:100%;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
        <tr><td style="background:#2563eb;padding:22px 28px;color:#fff">
          <h1 style="margin:0;font-size:20px">New support request</h1>
        </td></tr>
        <tr><td style="padding:26px 28px">
          <table width="100%" cellpadding="6" cellspacing="0" style="font-size:14px">
            <tr><td style="width:120px;color:#6b7280">Name</td><td><strong>{safe_name}</strong></td></tr>
            <tr><td style="color:#6b7280">Email</td><td>{safe_email}</td></tr>
            <tr><td style="color:#6b7280">UI language</td><td>{language_label}</td></tr>
            <tr><td style="color:#6b7280">Subject</td><td>{safe_subject}</td></tr>
          </table>
          <div style="margin-top:22px;padding-top:20px;border-top:1px solid #e5e7eb">
            <p style="margin:0 0 10px;color:#6b7280;font-size:13px;font-weight:700">ISSUE DESCRIPTION</p>
            <p style="margin:0;font-size:14px;line-height:1.7;white-space:normal">{safe_description}</p>
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Support] {subject}"
    msg["From"] = email_from
    msg["To"] = to_email
    msg["Reply-To"] = sender_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
        )
        logger.info("Support request email sent to configured recipient")
        return True
    except Exception as exc:
        logger.error("Failed to send support request email: %s", exc)
        raise


async def send_account_deletion_request_email(
    to_email: str,
    account_email: str,
    user_id: int | None,
    reason: str,
    notes: str,
    ui_language: str,
    authenticated: bool,
) -> bool:
    """Send an account deletion request to the configured privacy contact."""
    smtp_user = str(get_runtime_config("SMTP_USER", required=False) or "")
    smtp_password = str(get_runtime_config("SMTP_PASSWORD", required=False) or "")
    if not smtp_user or not smtp_password:
        logger.error("SMTP is not configured; account deletion request was not sent")
        return False

    smtp_host = str(get_runtime_config("SMTP_HOST", required=False) or "smtp.gmail.com")
    smtp_port = int(get_runtime_config("SMTP_PORT", required=False) or 587)
    email_from = str(get_runtime_config("EMAIL_FROM", required=False) or smtp_user)

    safe_email = escape(account_email)
    safe_reason = escape(reason)
    safe_notes = escape(notes or "Not provided").replace("\n", "<br>")
    user_id_text = str(user_id) if user_id is not None else "Not authenticated"
    auth_text = "Authenticated account" if authenticated else "Public submission"
    language_label = "English" if ui_language == "en" else "Tiếng Việt"

    plain_body = (
        "Account deletion request\n\n"
        f"Account email: {account_email}\n"
        f"User ID: {user_id_text}\n"
        f"Identity source: {auth_text}\n"
        f"UI language: {language_label}\n"
        f"Reason: {reason}\n\n"
        f"Additional notes:\n{notes or 'Not provided'}\n"
    )
    html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px;background:#f4f6f8;font-family:Arial,sans-serif;color:#1f2937">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
             style="max-width:100%;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
        <tr><td style="background:#b91c1c;padding:22px 28px;color:#fff">
          <h1 style="margin:0;font-size:20px">Account deletion request</h1>
        </td></tr>
        <tr><td style="padding:26px 28px">
          <table width="100%" cellpadding="6" cellspacing="0" style="font-size:14px">
            <tr><td style="width:130px;color:#6b7280">Account email</td><td><strong>{safe_email}</strong></td></tr>
            <tr><td style="color:#6b7280">User ID</td><td>{user_id_text}</td></tr>
            <tr><td style="color:#6b7280">Identity source</td><td>{auth_text}</td></tr>
            <tr><td style="color:#6b7280">UI language</td><td>{language_label}</td></tr>
            <tr><td style="color:#6b7280">Reason</td><td>{safe_reason}</td></tr>
          </table>
          <div style="margin-top:22px;padding-top:20px;border-top:1px solid #e5e7eb">
            <p style="margin:0 0 10px;color:#6b7280;font-size:13px;font-weight:700">ADDITIONAL NOTES</p>
            <p style="margin:0;font-size:14px;line-height:1.7">{safe_notes}</p>
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Account deletion] {account_email}"
    msg["From"] = email_from
    msg["To"] = to_email
    msg["Reply-To"] = account_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
        )
        logger.info("Account deletion request sent to configured recipient")
        return True
    except Exception as exc:
        logger.error("Failed to send account deletion request: %s", exc)
        raise
