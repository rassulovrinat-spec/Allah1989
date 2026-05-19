import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db, init_db
from app.models import Order, Factory, OrderStatus, User, ActivityLog, SiteSettings
from app.auth import verify_password, hash_password, make_token, decode_token
from app.email_service import send_factory_email, send_admin_notification

SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")

app = FastAPI(title="Мебельные заявки")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["dt"] = lambda x: x.strftime("%d.%m.%Y %H:%M") if x else "—"
templates.env.filters["date"] = lambda x: x.strftime("%d.%m.%Y") if x else "—"

static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

STATUS_LABELS = {
    "new": "Новая",
    "sent_to_factory": "Отправлено",
    "accepted": "Принято",
    "rejected": "Отклонено",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def get_user(request: Request, db: Session):
    token = request.cookies.get("session")
    if not token:
        return None
    data = decode_token(token)
    if not data:
        return None
    user = db.query(User).filter(User.id == data["user_id"]).first()
    return user if user and user.is_active else None


def get_settings(db: Session) -> SiteSettings:
    s = db.query(SiteSettings).first()
    if not s:
        s = SiteSettings()
        db.add(s)
        db.commit()
    return s


def ctx(request: Request, db: Session, user: User, **extra):
    s = get_settings(db)
    return {
        "request": request,
        "me": user,
        "theme": s.theme,
        "primary_color": s.primary_color,
        "status_labels": STATUS_LABELS,
        **extra,
    }


def log(db: Session, user: User, action: str, request: Request = None):
    ip = request.client.host if request else None
    db.add(ActivityLog(username=user.username, role=user.role, action=action, ip_address=ip))
    db.commit()


# ── startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()


# ── auth ──────────────────────────────────────────────────────────────────────

@app.get("/")
def root(request: Request):
    if request.cookies.get("session"):
        return RedirectResponse("/orders")
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Неверный логин или пароль",
        })
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

    return templates.TemplateResponse("order_detail.html", ctx(request, db, user, order=order))


@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status != OrderStatus.new:
        return RedirectResponse(f"/orders/{order_id}?err=Нельзя подтвердить эту заявку", 303)

    order.confirmation_token = str(uuid.uuid4())
    order.status = OrderStatus.sent_to_factory
    order.sent_to_factory_at = datetime.utcnow()
    db.commit()

    confirm_url = f"{SITE_URL}/confirm/{order.confirmation_token}"
    try:
        send_factory_email(order, confirm_url)
        msg = "Заявка подтверждена — письмо отправлено фабрике"
    except Exception as e:
        msg = f"Статус обновлён, но email не отправлен: {e}"

    log(db, user, f"Подтверждена заявка №{order_id} → отправлено фабрике «{order.factory_name}»", request)
    return RedirectResponse(f"/orders/{order_id}?msg={msg}", 303)


@app.post("/orders/{order_id}/reject")
def reject_order(order_id: int, request: Request, reason: str = Form(""),
                 db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user:
        return RedirectResponse("/login", 303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status not in [OrderStatus.new, OrderStatus.sent_to_factory]:
        return RedirectResponse(f"/orders/{order_id}?err=Нельзя отклонить эту заявку", 303)

    order.status = OrderStatus.rejected
    order.rejection_reason = reason or None
    db.commit()
    log(db, user, f"Отклонена заявка №{order_id} (клиент: {order.client_name})", request)
    return RedirectResponse(f"/orders/{order_id}?msg=Заявка отклонена", 303)


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
             "message": f"Заявка №{order.id} уже была подтверждена ранее."})

    order.status = OrderStatus.accepted
    order.factory_confirmed_at = datetime.utcnow()
    db.commit()
    try:
        send_admin_notification(order)
    except Exception:
        pass

    return templates.TemplateResponse("confirm_result.html",
        {"request": request, "success": True, "order": order,
         "message": f"Заявка №{order.id} успешно подтверждена. Спасибо!"})


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
                db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    db.add(Factory(name=name.strip(), email=email.strip()))
    db.commit()
    log(db, user, f"Добавлена фабрика «{name.strip()}»", request)
    return RedirectResponse("/factories?msg=Фабрика добавлена", 303)


@app.post("/factories/{factory_id}/delete")
def delete_factory(factory_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)
    factory = db.query(Factory).filter(Factory.id == factory_id).first()
    if factory:
        log(db, user, f"Удалена фабрика «{factory.name}»", request)
        db.delete(factory)
        db.commit()
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

    db.add(User(
        username=username.strip(),
        password_hash=hash_password(password),
        display_name=display_name.strip() or None,
        role=role,
    ))
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
        log(db, user, f"Сброшен пароль пользователя «{target.username}»", request)
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
        state = "активирован" if target.is_active else "деактивирован"
        log(db, user, f"Пользователь «{target.username}» {state}", request)
    return RedirectResponse("/users?msg=Статус обновлён", 303)


@app.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/orders", 303)

    target = db.query(User).filter(User.id == user_id).first()
    if target and target.role != "admin":
        log(db, user, f"Удалён пользователь «{target.username}»", request)
        db.delete(target)
        db.commit()
    return RedirectResponse("/users?msg=Пользователь удалён", 303)


# ── activity log (admin) ──────────────────────────────────────────────────────

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
    s.theme = theme
    s.primary_color = primary_color
    db.commit()
    log(db, user, f"Изменены настройки: тема={theme}, цвет={primary_color}", request)
    return RedirectResponse("/settings?msg=Настройки сохранены", 303)
