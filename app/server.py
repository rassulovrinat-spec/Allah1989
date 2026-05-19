import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, BadSignature
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db, init_db
from app.models import Order, Factory, OrderStatus
from app.email_service import send_factory_email, send_admin_notification

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")

app = FastAPI(title="МебельЗаявки")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["dt"] = lambda x: x.strftime("%d.%m.%Y %H:%M") if x else "—"

static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

serializer = URLSafeTimedSerializer(SECRET_KEY)

STATUS_LABELS = {
    "new": "Новая",
    "sent_to_factory": "Отправлено фабрике",
    "accepted": "Принято фабрикой",
    "rejected": "Отклонено",
}
STATUS_COLORS = {
    "new": "warning text-dark",
    "sent_to_factory": "info text-dark",
    "accepted": "success",
    "rejected": "danger",
}


def get_session_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=86400 * 7)
        return data.get("user") if data.get("user") == ADMIN_USERNAME else None
    except BadSignature:
        return None


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root(request: Request):
    if get_session_user(request):
        return RedirectResponse("/orders")
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = serializer.dumps({"user": username})
        resp = RedirectResponse("/orders", status_code=303)
        resp.set_cookie("session", token, httponly=True, max_age=86400 * 7)
        return resp
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Неверный логин или пароль",
    })


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp


@app.get("/orders", response_class=HTMLResponse)
def orders_list(request: Request, status: str = None, db: Session = Depends(get_db)):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)

    query = db.query(Order)
    if status:
        query = query.filter(Order.status == status)
    orders = query.order_by(Order.created_at.desc()).all()
    counts = {s: db.query(Order).filter(Order.status == s).count() for s in STATUS_LABELS}

    return templates.TemplateResponse("orders.html", {
        "request": request,
        "orders": orders,
        "current_status": status,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "counts": counts,
    })


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    return templates.TemplateResponse("order_detail.html", {
        "request": request,
        "order": order,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
    })


@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status != OrderStatus.new:
        return RedirectResponse(f"/orders/{order_id}?err=Нельзя подтвердить эту заявку", status_code=303)

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

    return RedirectResponse(f"/orders/{order_id}?msg={msg}", status_code=303)


@app.post("/orders/{order_id}/reject")
def reject_order(
    order_id: int,
    request: Request,
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status not in [OrderStatus.new, OrderStatus.sent_to_factory]:
        return RedirectResponse(f"/orders/{order_id}?err=Нельзя отклонить эту заявку", status_code=303)

    order.status = OrderStatus.rejected
    order.rejection_reason = reason or None
    db.commit()

    return RedirectResponse(f"/orders/{order_id}?msg=Заявка отклонена", status_code=303)


@app.get("/confirm/{token}", response_class=HTMLResponse)
def factory_confirm(token: str, request: Request, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.confirmation_token == token).first()

    if not order:
        return templates.TemplateResponse("confirm_result.html", {
            "request": request,
            "success": False,
            "message": "Ссылка недействительна или заявка не найдена.",
        })

    if order.status == OrderStatus.accepted:
        return templates.TemplateResponse("confirm_result.html", {
            "request": request,
            "success": True,
            "order": order,
            "message": f"Заявка №{order.id} уже была подтверждена ранее.",
        })

    order.status = OrderStatus.accepted
    order.factory_confirmed_at = datetime.utcnow()
    db.commit()

    try:
        send_admin_notification(order)
    except Exception:
        pass

    return templates.TemplateResponse("confirm_result.html", {
        "request": request,
        "success": True,
        "order": order,
        "message": f"Заявка №{order.id} успешно подтверждена. Спасибо!",
    })


@app.get("/factories", response_class=HTMLResponse)
def factories_list(request: Request, db: Session = Depends(get_db)):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)
    factories = db.query(Factory).order_by(Factory.name).all()
    return templates.TemplateResponse("factories.html", {"request": request, "factories": factories})


@app.post("/factories/add")
def add_factory(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)
    db.add(Factory(name=name.strip(), email=email.strip()))
    db.commit()
    return RedirectResponse("/factories?msg=Фабрика добавлена", status_code=303)


@app.post("/factories/{factory_id}/delete")
def delete_factory(factory_id: int, request: Request, db: Session = Depends(get_db)):
    if not get_session_user(request):
        return RedirectResponse("/login", status_code=303)
    factory = db.query(Factory).filter(Factory.id == factory_id).first()
    if factory:
        db.delete(factory)
        db.commit()
    return RedirectResponse("/factories?msg=Фабрика удалена", status_code=303)
