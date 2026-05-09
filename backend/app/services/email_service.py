import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

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


async def send_password_reset_email(to_email: str, otp_code: str) -> None:
    """Send OTP reset code to `to_email` via SMTP (TLS/STARTTLS on port 587)."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured — skipping email send (OTP: %s)", otp_code)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Mã xác nhận đặt lại mật khẩu"
    msg["From"] = settings.EMAIL_FROM or settings.SMTP_USER
    msg["To"] = to_email

    msg.attach(MIMEText(_build_otp_html(otp_code), "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info("Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send reset email to %s: %s", to_email, exc)
        raise
