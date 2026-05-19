import os
import uuid
import shutil
from datetime import datetime
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db, init_db
from app.models import (Order, Factory, OrderStatus, User, ActivityLog,
                        SiteSettings, PriceBatch, PriceItem, OrderAttachment)
from app.auth import verify_password, hash_password, make_token, decode_token
from app.email_service import send_factory_email, send_admin_notification
from app.price_parser import parse_price_file

SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")
COMMISSION_RATE = 0.03


def send_telegram_message(chat_id, text: str):
    """Отправить сообщение менеджеру в Telegram через Bot API."""
    import urllib.request, json as _json
    token = os.getenv("BOT_TOKEN", "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = _json.dumps({"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

app = FastAPI(title="Мебельные заявки")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["dt"]   = lambda x: x.strftime("%d.%m.%Y %H:%M") if x else "—"
templates.env.filters["date"] = lambda x: x.strftime("%d.%m.%Y") if x else "—"
templates.env.filters["rub"]  = lambda x: f"{x:,.0f} ₽".replace(",", " ") if x else "—"

STATIC_DIR  = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

STATUS_LABELS = {
    "new": "Новая", "sent_to_factory": "Отправлено",
    "accepted": "Принято", "rejected": "Отклонено",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def get_user(request: Request, db: Session):
    token = request.cookies.get("session")
    if not token:
        return None
    data = decode_token(token)
    if not data:
        return None
    user = db.query(User).filter(User.id == data["user_id"]).first()
    return user if user and user.is_active else None


def get_settings(db: Session):
    s = db.query(SiteSettings).first()
    if not s:
        s = SiteSettings(); db.add(s); db.commit()
    return s


def ctx(request: Request, db: Session, user: User, **extra):
    s = get_settings(db)
    return {"request": request, "me": user, "theme": s.theme,
            "primary_color": s.primary_color, "status_labels": STATUS_LABELS, **extra}


def log(db: Session, user: User, action: str, request: Request = None):
    ip = request.client.host if request else None
    db.add(ActivityLog(username=user.username, role=user.role,
                       action=action, ip_address=ip))
    db.commit()


@app.on_event("startup")
def startup():
    init_db()


# ── auth ──────────────────────────────────────────────────────────────────────

@app.get("/")
def root(request: Request):
    return RedirectResponse("/orders" if request.cookies.get("session") else "/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html",
            {"request": request, "error": "Неверный логин или пароль"})
    user.last_login_at = datetime.utcnow()
    db.commit()
    log(db, user, "Вход в систему", request)
    resp = RedirectResponse("/orders", status_code=303)
    resp.set_cookie("session", make_token(user.id, user.username, user.role),
                    httponly=True, max_age=86400 * 7)
    return resp


@app.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if user:
        log(db, user, "Выход из системы", request)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp


# ── orders ────────────────────────────────────────────────────────────────────

@app.get("/orders", response_class=HTMLResponse)
def orders_list(request: Request, status: str = None, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    orders = q.order_by(Order.created_at.desc()).all()
    counts = {s: db.query(Order).filter(Order.status == s).count() for s in STATUS_LABELS}
    return templates.TemplateResponse("orders.html", ctx(request, db, user,
        orders=orders, current_status=status, counts=counts))


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404)
    attachments = db.query(OrderAttachment).filter(OrderAttachment.order_id == order_id).all()
    commission = round(order.order_amount * COMMISSION_RATE, 2) if order.order_amount else None
    return templates.TemplateResponse("order_detail.html", ctx(request, db, user,
        order=order, attachments=attachments, commission=commission,
        commission_rate=int(COMMISSION_RATE * 100)))


@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status != OrderStatus.new:
        return RedirectResponse(f"/orders/{order_id}?err=Нельзя подтвердить", 303)
    order.confirmation_token = str(uuid.uuid4())
    order.status = OrderStatus.sent_to_factory
    order.sent_to_factory_at = datetime.utcnow()
    db.commit()
    confirm_url = f"{SITE_URL}/confirm/{order.confirmation_token}"
    try:
        send_factory_email(order, confirm_url)
        msg = "Подтверждено — письмо отправлено фабрике"
    except Exception as e:
        msg = f"Статус обновлён, email не отправлен: {e}"
    log(db, user, f"Подтверждена заявка №{order_id} → фабрика «{order.factory_name}»", request)
    return RedirectResponse(f"/orders/{order_id}?msg={msg}", 303)


@app.post("/orders/{order_id}/reject")
def reject_order(order_id: int, request: Request, reason: str = Form(""),
                 db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status not in [OrderStatus.new, OrderStatus.sent_to_factory]:
        return RedirectResponse(f"/orders/{order_id}?err=Нельзя отклонить", 303)
    order.status = OrderStatus.rejected
    order.rejection_reason = reason or None
    db.commit()
    log(db, user, f"Отклонена заявка №{order_id}", request)
    return RedirectResponse(f"/orders/{order_id}?msg=Заявка отклонена", 303)


@app.post("/orders/{order_id}/upload")
def upload_attachment(order_id: int, request: Request,
                      file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404)
    order_dir = os.path.join(UPLOADS_DIR, str(order_id))
    os.makedirs(order_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    saved_name = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(order_dir, saved_name)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    db.add(OrderAttachment(order_id=order_id, filename=saved_name,
                           original_name=file.filename, uploaded_by=user.username))
    db.commit()
    log(db, user, f"Прикреплён файл «{file.filename}» к заявке №{order_id}", request)
    return RedirectResponse(f"/orders/{order_id}?msg=Файл прикреплён", 303)


@app.get("/orders/{order_id}/download/{filename}")
def download_attachment(order_id: int, filename: str, request: Request,
                        db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    att = db.query(OrderAttachment).filter(
        OrderAttachment.order_id == order_id,
        OrderAttachment.filename == filename
    ).first()
    if not att:
        raise HTTPException(404)
    path = os.path.join(UPLOADS_DIR, str(order_id), filename)
    return FileResponse(path, filename=att.original_name or filename)


# ── factory confirmation (public) ─────────────────────────────────────────────

@app.get("/confirm/{token}", response_class=HTMLResponse)
def factory_confirm(token: str, request: Request, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.confirmation_token == token).first()
    if not order:
        return templates.TemplateResponse("confirm_result.html",
            {"request": request, "success": False, "message": "Ссылка недействительна."})
    if order.status == OrderStatus.accepted:
        return templates.TemplateResponse("confirm_result.html",
            {"request": request, "success": True, "order": order,
             "message": f"Заявка №{order.id} уже подтверждена."})
    order.status = OrderStatus.accepted
    order.factory_confirmed_at = datetime.utcnow()
    db.commit()
    try:
        send_admin_notification(order)
    except Exception:
        pass
    # Уведомить менеджера в Telegram если у него есть chat_id
    if order.manager_id:
        manager = db.query(User).filter(User.id == order.manager_id).first()
        if manager and manager.telegram_id:
            amount_str = f"{int(order.order_amount):,} ₽".replace(",", " ") if order.order_amount else "—"
            send_telegram_message(
                manager.telegram_id,
                f"✅ *Заявка №{order.id} подтверждена фабрикой!*\n\n"
                f"Клиент: {order.client_name}\n"
                f"Фабрика: {order.factory_name}\n"
                f"Модель: {order.model}\n"
                f"Сумма: {amount_str}"
            )
    return templates.TemplateResponse("confirm_result.html",
        {"request": request, "success": True, "order": order,
         "message": f"Заявка №{order.id} подтверждена. Спасибо!"})


# ── price list ────────────────────────────────────────────────────────────────

@app.get("/pricelist", response_class=HTMLResponse)
def pricelist_page(request: Request, batch_id: str = None, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    batches = db.query(PriceBatch).order_by(PriceBatch.uploaded_at.desc()).all()
    items = []
    selected = None
    if batch_id:
        selected = db.query(PriceBatch).filter(PriceBatch.uuid == batch_id).first()
        if selected:
            items = db.query(PriceItem).filter(PriceItem.batch_uuid == batch_id).all()
    elif batches:
        selected = batches[0]
        items = db.query(PriceItem).filter(PriceItem.batch_uuid == selected.uuid).all()
    return templates.TemplateResponse("pricelist.html", ctx(request, db, user,
        batches=batches, items=items, selected=selected))


@app.post("/pricelist/upload")
async def upload_pricelist(request: Request, factory_name: str = Form(""),
                           file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/pricelist", 303)
    contents = await file.read()
    try:
        items = parse_price_file(contents, file.filename or "")
    except Exception as e:
        return RedirectResponse(f"/pricelist?err={e}", 303)
    if not items:
        return RedirectResponse("/pricelist?err=Файл пустой или не распознан", 303)
    batch_uuid = str(uuid.uuid4())
    batch = PriceBatch(uuid=batch_uuid, factory_name=factory_name or file.filename,
                       filename=file.filename, item_count=len(items),
                       uploaded_by=user.username)
    db.add(batch)
    db.bulk_insert_mappings(PriceItem, [
        {"batch_uuid": batch_uuid, **item} for item in items
    ])
    db.commit()
    log(db, user, f"Загружен прайс «{file.filename}» ({len(items)} позиций)", request)
    return RedirectResponse(f"/pricelist?batch_id={batch_uuid}&msg=Прайс загружен: {len(items)} позиций", 303)


@app.post("/pricelist/{batch_uuid}/delete")
def delete_pricelist(batch_uuid: str, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/pricelist", 303)
    batch = db.query(PriceBatch).filter(PriceBatch.uuid == batch_uuid).first()
    if batch:
        db.query(PriceItem).filter(PriceItem.batch_uuid == batch_uuid).delete()
        db.delete(batch)
        db.commit()
        log(db, user, f"Удалён прайс «{batch.filename}»", request)
    return RedirectResponse("/pricelist?msg=Прайс удалён", 303)


# ── report ────────────────────────────────────────────────────────────────────

@app.get("/report", response_class=HTMLResponse)
def report_page(request: Request, month: int = None, year: int = None,
                db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)

    now = datetime.utcnow()
    month = month or now.month
    year  = year  or now.year

    q = db.query(Order).filter(
        Order.status == OrderStatus.accepted,
        Order.order_amount.isnot(None),
    )
    # Admin sees all; manager sees own
    if user.role != "admin":
        q = q.filter(Order.manager_id == user.id)

    # Filter by month/year using Python (SQLite has limited date funcs)
    all_orders = q.all()
    period_orders = [
        o for o in all_orders
        if o.factory_confirmed_at
        and o.factory_confirmed_at.month == month
        and o.factory_confirmed_at.year == year
    ]

    # Group by manager
    managers = {}
    for o in period_orders:
        key = o.manager_username or "—"
        if key not in managers:
            managers[key] = {"username": key, "orders": [], "total": 0, "commission": 0}
        managers[key]["orders"].append(o)
        managers[key]["total"] += o.order_amount or 0
        managers[key]["commission"] += (o.order_amount or 0) * COMMISSION_RATE

    rows = sorted(managers.values(), key=lambda x: x["commission"], reverse=True)
    for r in rows:
        r["commission"] = round(r["commission"], 2)
        r["total"] = round(r["total"], 2)

    # Month navigation list
    months = ["Январь","Февраль","Март","Апрель","Май","Июнь",
              "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]

    return templates.TemplateResponse("report.html", ctx(request, db, user,
        rows=rows, month=month, year=year, months=months,
        total_amount=sum(r["total"] for r in rows),
        total_commission=round(sum(r["commission"] for r in rows), 2),
        commission_rate=int(COMMISSION_RATE * 100),
        period_orders=period_orders))


# ── factories (admin) ─────────────────────────────────────────────────────────

@app.get("/factories", response_class=HTMLResponse)
def factories_list(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    factories = db.query(Factory).order_by(Factory.name).all()
    return templates.TemplateResponse("factories.html", ctx(request, db, user, factories=factories))


@app.post("/factories/add")
def add_factory(request: Request, name: str = Form(...), email: str = Form(...),
                reply_email: str = Form(""), db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    db.add(Factory(name=name.strip(), email=email.strip(),
                   reply_email=reply_email.strip() or None))
    db.commit()
    log(db, user, f"Добавлена фабрика «{name}»", request)
    return RedirectResponse("/factories?msg=Фабрика добавлена", 303)


@app.post("/factories/{factory_id}/delete")
def delete_factory(factory_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    f = db.query(Factory).filter(Factory.id == factory_id).first()
    if f:
        log(db, user, f"Удалена фабрика «{f.name}»", request)
        db.delete(f); db.commit()
    return RedirectResponse("/factories?msg=Фабрика удалена", 303)


# ── users (admin) ─────────────────────────────────────────────────────────────

@app.get("/users", response_class=HTMLResponse)
def users_list(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse("users.html", ctx(request, db, user, users=users))


@app.post("/users/add")
def add_user(request: Request, username: str = Form(...), display_name: str = Form(""),
             password: str = Form(...), role: str = Form("manager"),
             db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    if db.query(User).filter(User.username == username).first():
        users = db.query(User).order_by(User.created_at).all()
        return templates.TemplateResponse("users.html", ctx(request, db, user,
            users=users, error=f"Пользователь «{username}» уже существует"))
    db.add(User(username=username.strip(), password_hash=hash_password(password),
                display_name=display_name.strip() or None, role=role))
    db.commit()
    log(db, user, f"Создан пользователь «{username}» (роль: {role})", request)
    return RedirectResponse("/users?msg=Пользователь создан", 303)


@app.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, new_password: str = Form(...),
                   db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    target = db.query(User).filter(User.id == user_id).first()
    if target:
        target.password_hash = hash_password(new_password)
        db.commit()
        log(db, user, f"Сброшен пароль «{target.username}»", request)
    return RedirectResponse("/users?msg=Пароль обновлён", 303)


@app.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.role != "admin":
        target.is_active = not target.is_active
        db.commit()
        log(db, user, f"{'Активирован' if target.is_active else 'Деактивирован'} «{target.username}»", request)
    return RedirectResponse("/users?msg=Статус обновлён", 303)


@app.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.role != "admin":
        log(db, user, f"Удалён «{target.username}»", request)
        db.delete(target); db.commit()
    return RedirectResponse("/users?msg=Пользователь удалён", 303)


@app.post("/users/me/update")
def update_my_profile(request: Request,
                      display_name: str = Form(""),
                      new_username: str = Form(""),
                      new_password: str = Form(""),
                      db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)
    if display_name.strip():
        user.display_name = display_name.strip()
    if new_username.strip() and new_username.strip() != user.username:
        if db.query(User).filter(User.username == new_username.strip()).first():
            users = db.query(User).order_by(User.created_at).all()
            return templates.TemplateResponse("users.html", ctx(request, db, user,
                users=users, profile_error="Логин уже занят"))
        user.username = new_username.strip()
    if new_password.strip():
        user.password_hash = hash_password(new_password.strip())
    db.commit()
    log(db, user, "Обновил свой профиль", request)
    # Обновляем сессию с новым логином
    from fastapi.responses import Response
    from app.auth import make_token
    resp = RedirectResponse("/users?msg=Профиль обновлён", 303)
    token = make_token(user.id, user.username, user.role)
    resp.set_cookie("session", token, httponly=True, max_age=86400*30, samesite="lax")
    return resp


# ── activity (admin) ──────────────────────────────────────────────────────────

@app.get("/activity", response_class=HTMLResponse)
def activity_log(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    logs = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(500).all()
    return templates.TemplateResponse("activity.html", ctx(request, db, user, logs=logs))


# ── settings (admin) ──────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    s = get_settings(db)
    return templates.TemplateResponse("settings.html", ctx(request, db, user, settings=s))


@app.post("/settings")
def save_settings(request: Request, theme: str = Form("light"),
                  primary_color: str = Form("indigo"), db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    s = get_settings(db)
    s.theme = theme; s.primary_color = primary_color
    db.commit()
    log(db, user, f"Настройки: тема={theme}, цвет={primary_color}", request)
    return RedirectResponse("/settings?msg=Настройки сохранены", 303)


# ── API для Telegram-бота ─────────────────────────────────────────────────────

@app.post("/api/verify-manager")
async def verify_manager(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    user = db.query(User).filter(User.username == data.get("username")).first()
    if not user or not user.is_active or not verify_password(data.get("password", ""), user.password_hash):
        return {"ok": False, "error": "Неверный логин или пароль"}
    if user.role not in ("admin", "manager"):
        return {"ok": False, "error": "Нет доступа"}
    # Сохраняем Telegram chat_id менеджера для уведомлений
    telegram_id = str(data.get("telegram_id", "")).strip()
    if telegram_id and user.telegram_id != telegram_id:
        user.telegram_id = telegram_id
        db.commit()
    return {"ok": True, "user_id": user.id, "username": user.username,
            "display_name": user.display_name or user.username, "role": user.role}


@app.post("/api/orders")
async def create_order_api(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    factory = db.query(Factory).filter(Factory.name == data.get("factory_name")).first()
    if not factory:
        return {"ok": False, "error": "Фабрика не найдена"}
    order = Order(
        client_name=data["client_name"],
        client_phone=data.get("client_phone"),
        client_email=data.get("client_email"),
        client_telegram_id=str(data.get("client_telegram_id", "")),
        factory_name=factory.name, factory_email=factory.email,
        category=data["category"], model=data["model"],
        dimensions=data.get("dimensions"), material=data.get("material"),
        color=data.get("color"), configuration=data.get("configuration"),
        quantity=data.get("quantity", 1), delivery_date=data.get("delivery_date"),
        comments=data.get("comments"), photo_url=data.get("photo_url"),
        order_amount=data.get("order_amount"),
        manager_id=data.get("manager_id"),
        manager_username=data.get("manager_username"),
    )
    db.add(order); db.commit(); db.refresh(order)
    return {"ok": True, "id": order.id}


@app.get("/api/factories")
def api_factories(db: Session = Depends(get_db)):
    return [{"id": f.id, "name": f.name} for f in db.query(Factory).order_by(Factory.name).all()]
