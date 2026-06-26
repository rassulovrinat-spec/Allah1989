import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")


def _send(to: str, subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.sendmail(SMTP_USER, to, msg.as_string())


def send_factory_email(order, confirm_url: str):
    rows = [
        ("Категория", order.category),
        ("Модель / Артикул", order.model),
        ("Размеры", order.dimensions or "—"),
        ("Материал / Обивка", order.material or "—"),
        ("Цвет", order.color or "—"),
        ("Комплектация", order.configuration or "—"),
        ("Количество", str(order.quantity)),
        ("Срок поставки", order.delivery_date or "—"),
        ("Дата возможной отгрузки", order.shipment_date or "—"),
        ("Комментарии", order.comments or "—"),
    ]
    rows_html = "".join(
        f'<tr style="border-bottom:1px solid #eee">'
        f'<td style="padding:10px 14px;background:#f8f8f8;font-weight:600;color:#555;width:40%;white-space:nowrap">{k}</td>'
        f'<td style="padding:10px 14px">{v}</td>'
        f'</tr>'
        for k, v in rows
    )
    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;color:#333">
<div style="background:#1a1a2e;padding:24px;border-radius:8px 8px 0 0">
  <h2 style="color:white;margin:0">Заявка на мебель №{order.id}</h2>
  <p style="color:#aaa;margin:6px 0 0">Требуется ваше подтверждение</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px">
  <table style="width:100%;border-collapse:collapse">{rows_html}</table>
  <div style="text-align:center;margin-top:32px">
    <a href="{confirm_url}"
       style="background:#198754;color:white;padding:14px 36px;text-decoration:none;border-radius:6px;font-size:16px;font-weight:bold;display:inline-block">
      ✓ Подтвердить заявку
    </a>
  </div>
  <p style="color:#999;font-size:12px;text-align:center;margin-top:20px">
    Нажав кнопку, вы подтверждаете принятие заявки в работу.
  </p>
</div>
</body></html>"""
    _send(order.factory_email, f"Заявка №{order.id} — требуется подтверждение", html)


def send_admin_notification(order):
    if not ADMIN_EMAIL:
        return
    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px">
<div style="background:#198754;padding:20px;border-radius:8px 8px 0 0">
  <h2 style="color:white;margin:0">✓ Фабрика подтвердила заявку №{order.id}</h2>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:20px;border-radius:0 0 8px 8px">
  <p><strong>Фабрика:</strong> {order.factory_name}</p>
  <p><strong>Клиент:</strong> {order.client_name}</p>
  <p><strong>Модель:</strong> {order.model}</p>
  <p><strong>Количество:</strong> {order.quantity}</p>
  <p style="color:#198754;font-weight:bold">Фабрика подтвердила принятие заявки в работу.</p>
</div>
</body></html>"""
    _send(ADMIN_EMAIL, f"✓ Фабрика подтвердила заявку №{order.id}", html)
