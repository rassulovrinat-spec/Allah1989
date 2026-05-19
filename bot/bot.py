import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal, init_db
from app.models import Order, Factory
from app.auth import verify_password

BOT_TOKEN = os.getenv("BOT_TOKEN")
SITE_URL   = os.getenv("SITE_URL", "http://localhost:8000")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

router = Router()

CATEGORIES = ["Диван", "Кровать", "Шкаф", "Стол", "Кухня", "Другое"]


# ── States ────────────────────────────────────────────────────────────────────

class Login(StatesGroup):
    username = State()
    password = State()

class Form(StatesGroup):
    name          = State()
    phone         = State()
    email         = State()
    factory       = State()
    category      = State()
    model         = State()
    dimensions    = State()
    material      = State()
    color         = State()
    configuration = State()
    quantity      = State()
    delivery      = State()
    comments      = State()
    photo         = State()
    amount        = State()
    confirm       = State()


# ── Helpers ───────────────────────────────────────────────────────────────────

def kb(*rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True, one_time_keyboard=True,
    )

def get_factory_names():
    db = SessionLocal()
    try:
        return [f.name for f in db.query(Factory).order_by(Factory.name).all()]
    finally:
        db.close()


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    data = await state.get_data()
    manager_id = data.get("manager_id")
    manager_name = data.get("manager_name")

    if manager_id:
        # Уже авторизован — сбрасываем только активную форму, сессию сохраняем
        await state.set_state(None)
        await message.answer(
            f"👋 С возвращением, *{manager_name}*!\n\n"
            "/order — создать заявку\n"
            "/whoami — кто я\n"
            "/logout — выйти из аккаунта",
            parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
        )
    else:
        # Не авторизован — сразу просим логин
        await state.clear()
        await state.set_state(Login.username)
        await message.answer(
            "👋 Добро пожаловать!\n\n"
            "Введите *логин* для входа в систему:",
            parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
        )


# ── /login (менеджеры) ────────────────────────────────────────────────────────

@router.message(Command("login"))
async def cmd_login(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("manager_id"):
        await message.answer(f"Вы уже авторизованы как {data.get('manager_name')}.\n"
                             "Для смены аккаунта: /logout", reply_markup=ReplyKeyboardRemove())
        return
    await state.clear()
    await state.set_state(Login.username)
    await message.answer("🔐 Вход для менеджеров\n\nВведите логин:", reply_markup=ReplyKeyboardRemove())


@router.message(Login.username)
async def login_username(message: types.Message, state: FSMContext):
    await state.update_data(login_username=message.text.strip())
    await state.set_state(Login.password)
    await message.answer("Введите пароль:")


@router.message(Login.password)
async def login_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    username = data.get("login_username", "")
    password = message.text.strip()

    telegram_id = str(message.from_user.id)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{SITE_URL}/api/verify-manager",
                                  json={"username": username, "password": password,
                                        "telegram_id": telegram_id},
                                  timeout=10)
            result = r.json()
    except Exception:
        db = SessionLocal()
        try:
            from app.models import User
            user = db.query(User).filter(User.username == username).first()
            if user and user.is_active and verify_password(password, user.password_hash):
                # Сохраняем telegram_id напрямую в БД при fallback
                if user.telegram_id != telegram_id:
                    user.telegram_id = telegram_id
                    db.commit()
                result = {"ok": True, "user_id": user.id, "username": user.username,
                          "display_name": user.display_name or user.username}
            else:
                result = {"ok": False, "error": "Неверный логин или пароль"}
        finally:
            db.close()

    if not result.get("ok"):
        await state.set_state(Login.username)
        await message.answer(f"❌ {result.get('error', 'Ошибка')}\n\nВведите логин заново:")
        return

    await state.update_data(
        manager_id=result["user_id"],
        manager_username=result["username"],
        manager_name=result["display_name"],
        login_username=None,
    )
    await state.set_state(None)
    await message.answer(
        f"✅ Добро пожаловать, *{result['display_name']}*!\n\n"
        "Теперь ваши заявки будут учитываться в отчёте менеджеров.\n"
        "/order — создать заявку\n"
        "/whoami — кто я\n"
        "/logout — выйти",
        parse_mode="Markdown"
    )


@router.message(Command("whoami"))
async def cmd_whoami(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("manager_id"):
        await message.answer(f"👤 Вы авторизованы как *{data['manager_name']}* (@{data['manager_username']})",
                             parse_mode="Markdown")
    else:
        await message.answer("Вы не авторизованы.\n/login — войти как менеджер")


@router.message(Command("logout"))
async def cmd_logout(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data.get("manager_name", "")
    await state.update_data(manager_id=None, manager_username=None, manager_name=None)
    await message.answer(f"👋 {name}, вы вышли из аккаунта.", reply_markup=ReplyKeyboardRemove())


# ── /order ────────────────────────────────────────────────────────────────────

@router.message(Command("order"))
async def cmd_order(message: types.Message, state: FSMContext):
    mgr_data = await state.get_data()
    manager_id = mgr_data.get("manager_id")
    manager_username = mgr_data.get("manager_username")
    manager_name = mgr_data.get("manager_name")
    await state.clear()
    if manager_id:
        await state.update_data(manager_id=manager_id,
                                manager_username=manager_username,
                                manager_name=manager_name)
    await state.set_state(Form.name)
    prefix = f"📋 Заявка от менеджера *{manager_name}*\n\n" if manager_name else "📋 *Оформление заявки*\n\n"
    await message.answer(f"{prefix}*Шаг 1 из 15*\n\nВведите имя клиента:",
                         parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    mgr_data = await state.get_data()
    mid = mgr_data.get("manager_id")
    mu  = mgr_data.get("manager_username")
    mn  = mgr_data.get("manager_name")
    await state.clear()
    if mid:
        await state.update_data(manager_id=mid, manager_username=mu, manager_name=mn)
    await message.answer("❌ Оформление отменено. /order — начать заново.", reply_markup=ReplyKeyboardRemove())


# ── Form steps ────────────────────────────────────────────────────────────────

@router.message(Form.name)
async def step_name(message: types.Message, state: FSMContext):
    await state.update_data(client_name=message.text.strip())
    await state.set_state(Form.phone)
    await message.answer("*Шаг 2 из 15*\n\nТелефон клиента:", parse_mode="Markdown")


@router.message(Form.phone)
async def step_phone(message: types.Message, state: FSMContext):
    await state.update_data(client_phone=message.text.strip())
    await state.set_state(Form.email)
    await message.answer("*Шаг 3 из 15*\n\nEmail клиента (или `-`):", parse_mode="Markdown")


@router.message(Form.email)
async def step_email(message: types.Message, state: FSMContext):
    v = message.text.strip()
    await state.update_data(client_email=None if v == "-" else v)
    names = get_factory_names()
    if not names:
        await message.answer("⚠️ Список фабрик пуст. /cancel")
        await state.clear()
        return
    await state.update_data(factory_list=names)
    await state.set_state(Form.factory)
    await message.answer("*Шаг 4 из 15*\n\nВыберите фабрику:",
                         parse_mode="Markdown", reply_markup=kb(*[[n] for n in names]))


@router.message(Form.factory)
async def step_factory(message: types.Message, state: FSMContext):
    data = await state.get_data()
    valid = data.get("factory_list", [])
    if message.text not in valid:
        await message.answer("Выберите из списка:", reply_markup=kb(*[[n] for n in valid]))
        return
    await state.update_data(factory_name=message.text)
    await state.set_state(Form.category)
    rows = [CATEGORIES[i:i+2] for i in range(0, len(CATEGORIES), 2)]
    await message.answer("*Шаг 5 из 15*\n\nКатегория мебели:",
                         parse_mode="Markdown", reply_markup=kb(*rows))


@router.message(Form.category)
async def step_category(message: types.Message, state: FSMContext):
    if message.text not in CATEGORIES:
        rows = [CATEGORIES[i:i+2] for i in range(0, len(CATEGORIES), 2)]
        await message.answer("Выберите из списка:", reply_markup=kb(*rows))
        return
    await state.update_data(category=message.text)
    await state.set_state(Form.model)
    await message.answer("*Шаг 6 из 15*\n\nМодель / артикул:",
                         parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())


@router.message(Form.model)
async def step_model(message: types.Message, state: FSMContext):
    await state.update_data(model=message.text.strip())
    await state.set_state(Form.dimensions)
    await message.answer("*Шаг 7 из 15*\n\nРазмеры Ш×Г×В (мм) или `-`:", parse_mode="Markdown")


@router.message(Form.dimensions)
async def step_dimensions(message: types.Message, state: FSMContext):
    v = message.text.strip()
    await state.update_data(dimensions=None if v == "-" else v)
    await state.set_state(Form.material)
    await message.answer("*Шаг 8 из 15*\n\nМатериал / обивка:", parse_mode="Markdown")


@router.message(Form.material)
async def step_material(message: types.Message, state: FSMContext):
    await state.update_data(material=message.text.strip())
    await state.set_state(Form.color)
    await message.answer("*Шаг 9 из 15*\n\nЦвет / расцветка:", parse_mode="Markdown")


@router.message(Form.color)
async def step_color(message: types.Message, state: FSMContext):
    await state.update_data(color=message.text.strip())
    await state.set_state(Form.configuration)
    await message.answer("*Шаг 10 из 15*\n\nКомплектация:", parse_mode="Markdown")


@router.message(Form.configuration)
async def step_config(message: types.Message, state: FSMContext):
    await state.update_data(configuration=message.text.strip())
    await state.set_state(Form.quantity)
    await message.answer("*Шаг 11 из 15*\n\nКоличество (шт):", parse_mode="Markdown")


@router.message(Form.quantity)
async def step_quantity(message: types.Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое число:")
        return
    await state.update_data(quantity=qty)
    await state.set_state(Form.delivery)
    await message.answer("*Шаг 12 из 15*\n\nСрок поставки (напр. `15.07.2025`):",
                         parse_mode="Markdown")


@router.message(Form.delivery)
async def step_delivery(message: types.Message, state: FSMContext):
    await state.update_data(delivery_date=message.text.strip())
    await state.set_state(Form.comments)
    await message.answer("*Шаг 13 из 15*\n\nКомментарии (или `-`):", parse_mode="Markdown")


@router.message(Form.comments)
async def step_comments(message: types.Message, state: FSMContext):
    v = message.text.strip()
    await state.update_data(comments=None if v == "-" else v)
    await state.set_state(Form.photo)
    await message.answer("*Шаг 14 из 15*\n\nФото / референс 📷\n(или `-` чтобы пропустить):",
                         parse_mode="Markdown")


@router.message(Form.photo, F.photo)
async def step_photo_img(message: types.Message, state: FSMContext):
    await state.update_data(photo_url=f"tg:{message.photo[-1].file_id}")
    await ask_amount(message, state)


@router.message(Form.photo)
async def step_photo_skip(message: types.Message, state: FSMContext):
    await state.update_data(photo_url=None)
    await ask_amount(message, state)


async def ask_amount(message: types.Message, state: FSMContext):
    await state.set_state(Form.amount)
    await message.answer("*Шаг 15 из 15*\n\nСумма заказа в рублях\n(или `-` если неизвестна):",
                         parse_mode="Markdown")


@router.message(Form.amount)
async def step_amount(message: types.Message, state: FSMContext):
    v = message.text.strip()
    amount = None
    if v != "-":
        try:
            amount = float(v.replace(",", ".").replace(" ", ""))
        except ValueError:
            await message.answer("Введите число (например: `150000`) или `-`:", parse_mode="Markdown")
            return
    await state.update_data(order_amount=amount)
    await show_summary(message, state)


async def show_summary(message: types.Message, state: FSMContext):
    d = await state.get_data()
    amt = f"{d.get('order_amount'):,.0f} ₽".replace(",", " ") if d.get("order_amount") else "—"
    text = (
        "📋 *Сводка заявки*\n\n"
        f"👤 *Клиент:* {d['client_name']}\n"
        f"📞 *Телефон:* {d.get('client_phone') or '—'}\n"
        f"📧 *Email:* {d.get('client_email') or '—'}\n\n"
        f"🏭 *Фабрика:* {d['factory_name']}\n"
        f"🛋 *Категория:* {d['category']}\n"
        f"📦 *Модель:* {d['model']}\n"
        f"📐 *Размеры:* {d.get('dimensions') or '—'}\n"
        f"🧵 *Материал:* {d.get('material') or '—'}\n"
        f"🎨 *Цвет:* {d.get('color') or '—'}\n"
        f"📝 *Комплектация:* {d.get('configuration') or '—'}\n"
        f"🔢 *Количество:* {d.get('quantity', 1)}\n"
        f"📅 *Срок:* {d.get('delivery_date') or '—'}\n"
        f"💬 *Комментарии:* {d.get('comments') or '—'}\n"
        f"🖼 *Фото:* {'Да ✓' if d.get('photo_url') else '—'}\n"
        f"💰 *Сумма:* {amt}\n"
    )
    if d.get("manager_name"):
        text += f"👔 *Менеджер:* {d['manager_name']}\n"
    text += "\nВсё верно?"
    await state.set_state(Form.confirm)
    await message.answer(text, parse_mode="Markdown",
                         reply_markup=kb(["✅ Подтвердить и отправить"], ["❌ Начать заново"]))


@router.message(Form.confirm, F.text == "✅ Подтвердить и отправить")
async def step_confirm(message: types.Message, state: FSMContext):
    d = await state.get_data()
    db = SessionLocal()
    try:
        factory = db.query(Factory).filter(Factory.name == d["factory_name"]).first()
        if not factory:
            await message.answer("⚠️ Фабрика не найдена. /order", reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return
        order = Order(
            client_name=d["client_name"],
            client_phone=d.get("client_phone"),
            client_email=d.get("client_email"),
            client_telegram_id=str(message.from_user.id),
            factory_name=factory.name, factory_email=factory.email,
            category=d["category"], model=d["model"],
            dimensions=d.get("dimensions"), material=d.get("material"),
            color=d.get("color"), configuration=d.get("configuration"),
            quantity=d.get("quantity", 1), delivery_date=d.get("delivery_date"),
            comments=d.get("comments"), photo_url=d.get("photo_url"),
            order_amount=d.get("order_amount"),
            manager_id=d.get("manager_id"),
            manager_username=d.get("manager_username"),
        )
        db.add(order); db.commit(); db.refresh(order)
        order_id = order.id
    finally:
        db.close()

    mid = d.get("manager_id")
    mu  = d.get("manager_username")
    mn  = d.get("manager_name")
    await state.clear()
    if mid:
        await state.update_data(manager_id=mid, manager_username=mu, manager_name=mn)

    await message.answer(
        f"✅ *Заявка №{order_id} создана!*\n\nОжидайте подтверждения.\n/order — новая заявка",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Form.confirm, F.text == "❌ Начать заново")
async def step_restart(message: types.Message, state: FSMContext):
    await cmd_order(message, state)


@router.message(Form.confirm)
async def step_confirm_invalid(message: types.Message, state: FSMContext):
    await message.answer("Используйте кнопки:",
                         reply_markup=kb(["✅ Подтвердить и отправить"], ["❌ Начать заново"]))


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher()
    dp.include_router(router)
    print("Бот запущен. Ctrl+C для остановки.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
