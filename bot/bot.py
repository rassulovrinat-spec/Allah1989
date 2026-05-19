import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal, init_db
from app.models import Order, Factory

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CATEGORIES = ["Диван", "Кровать", "Шкаф", "Стол", "Кухня", "Другое"]


class Form(StatesGroup):
    name = State()
    phone = State()
    email = State()
    factory = State()
    category = State()
    model = State()
    dimensions = State()
    material = State()
    color = State()
    configuration = State()
    quantity = State()
    delivery = State()
    comments = State()
    photo = State()
    confirm = State()


def kb(*rows, resize=True):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=resize,
        one_time_keyboard=True,
    )


def get_factory_names():
    db = SessionLocal()
    try:
        return [f.name for f in db.query(Factory).order_by(Factory.name).all()]
    finally:
        db.close()


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать!\n\nЯ помогу оформить заявку на мебель.\nНажмите /order чтобы начать.",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("order"))
async def cmd_order(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.name)
    await message.answer(
        "📋 *Оформление заявки*\n\n*Шаг 1 из 14*\n\nВведите ваше полное имя:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Оформление отменено.\nНажмите /order чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Form.name)
async def step_name(message: types.Message, state: FSMContext):
    await state.update_data(client_name=message.text.strip())
    await state.set_state(Form.phone)
    await message.answer("*Шаг 2 из 14*\n\nВведите ваш контактный телефон:", parse_mode="Markdown")


@dp.message(Form.phone)
async def step_phone(message: types.Message, state: FSMContext):
    await state.update_data(client_phone=message.text.strip())
    await state.set_state(Form.email)
    await message.answer("*Шаг 3 из 14*\n\nВведите ваш email\n(или `-` если нет):", parse_mode="Markdown")


@dp.message(Form.email)
async def step_email(message: types.Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(client_email=None if val == "-" else val)

    factory_names = get_factory_names()
    if not factory_names:
        await message.answer("⚠️ Список фабрик пуст. Обратитесь к администратору.\nИспользуйте /cancel.")
        await state.clear()
        return

    await state.update_data(factory_list=factory_names)
    await state.set_state(Form.factory)
    await message.answer(
        "*Шаг 4 из 14*\n\nВыберите фабрику:",
        parse_mode="Markdown",
        reply_markup=kb(*[[n] for n in factory_names]),
    )


@dp.message(Form.factory)
async def step_factory(message: types.Message, state: FSMContext):
    data = await state.get_data()
    valid = data.get("factory_list", [])
    if message.text not in valid:
        await message.answer("Пожалуйста, выберите фабрику из списка:", reply_markup=kb(*[[n] for n in valid]))
        return
    await state.update_data(factory_name=message.text)
    await state.set_state(Form.category)
    cat_rows = [CATEGORIES[i : i + 2] for i in range(0, len(CATEGORIES), 2)]
    await message.answer("*Шаг 5 из 14*\n\nВыберите категорию мебели:", parse_mode="Markdown", reply_markup=kb(*cat_rows))


@dp.message(Form.category)
async def step_category(message: types.Message, state: FSMContext):
    if message.text not in CATEGORIES:
        cat_rows = [CATEGORIES[i : i + 2] for i in range(0, len(CATEGORIES), 2)]
        await message.answer("Выберите категорию из списка:", reply_markup=kb(*cat_rows))
        return
    await state.update_data(category=message.text)
    await state.set_state(Form.model)
    await message.answer("*Шаг 6 из 14*\n\nВведите модель / артикул:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())


@dp.message(Form.model)
async def step_model(message: types.Message, state: FSMContext):
    await state.update_data(model=message.text.strip())
    await state.set_state(Form.dimensions)
    await message.answer(
        "*Шаг 7 из 14*\n\nВведите размеры (Ш×Г×В в мм)\nНапример: `1200×800×750`\nИли `-` если не знаете:",
        parse_mode="Markdown",
    )


@dp.message(Form.dimensions)
async def step_dimensions(message: types.Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(dimensions=None if val == "-" else val)
    await state.set_state(Form.material)
    await message.answer("*Шаг 8 из 14*\n\nВведите материал / обивку:", parse_mode="Markdown")


@dp.message(Form.material)
async def step_material(message: types.Message, state: FSMContext):
    await state.update_data(material=message.text.strip())
    await state.set_state(Form.color)
    await message.answer("*Шаг 9 из 14*\n\nВведите цвет / расцветку:", parse_mode="Markdown")


@dp.message(Form.color)
async def step_color(message: types.Message, state: FSMContext):
    await state.update_data(color=message.text.strip())
    await state.set_state(Form.configuration)
    await message.answer("*Шаг 10 из 14*\n\nОпишите комплектацию\n(что входит в заказ):", parse_mode="Markdown")


@dp.message(Form.configuration)
async def step_config(message: types.Message, state: FSMContext):
    await state.update_data(configuration=message.text.strip())
    await state.set_state(Form.quantity)
    await message.answer("*Шаг 11 из 14*\n\nВведите количество единиц:", parse_mode="Markdown")


@dp.message(Form.quantity)
async def step_quantity(message: types.Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите целое положительное число (например: 1):")
        return
    await state.update_data(quantity=qty)
    await state.set_state(Form.delivery)
    await message.answer(
        "*Шаг 12 из 14*\n\nУкажите желаемый срок поставки:\nНапример: `15.07.2025` или `2 недели`",
        parse_mode="Markdown",
    )


@dp.message(Form.delivery)
async def step_delivery(message: types.Message, state: FSMContext):
    await state.update_data(delivery_date=message.text.strip())
    await state.set_state(Form.comments)
    await message.answer(
        "*Шаг 13 из 14*\n\nДополнительные комментарии\n(или `-` если нет):",
        parse_mode="Markdown",
    )


@dp.message(Form.comments)
async def step_comments(message: types.Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(comments=None if val == "-" else val)
    await state.set_state(Form.photo)
    await message.answer(
        "*Шаг 14 из 14*\n\nПрикрепите фото / референс 📷\nИли напишите `-` чтобы пропустить:",
        parse_mode="Markdown",
    )


@dp.message(Form.photo, F.photo)
async def step_photo_img(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo_url=f"tg:{file_id}")
    await show_summary(message, state)


@dp.message(Form.photo)
async def step_photo_skip(message: types.Message, state: FSMContext):
    await state.update_data(photo_url=None)
    await show_summary(message, state)


async def show_summary(message: types.Message, state: FSMContext):
    d = await state.get_data()
    text = (
        "📋 *Сводка заявки*\n\n"
        f"👤 *Имя:* {d['client_name']}\n"
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
        f"🖼 *Фото:* {'Прикреплено ✓' if d.get('photo_url') else '—'}\n\n"
        "Всё верно?"
    )
    await state.set_state(Form.confirm)
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=kb(["✅ Подтвердить и отправить"], ["❌ Начать заново"]),
    )


@dp.message(Form.confirm, F.text == "✅ Подтвердить и отправить")
async def step_confirm(message: types.Message, state: FSMContext):
    d = await state.get_data()
    db = SessionLocal()
    try:
        factory = db.query(Factory).filter(Factory.name == d["factory_name"]).first()
        if not factory:
            await message.answer(
                "⚠️ Ошибка: фабрика не найдена. Начните заново: /order",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            return

        order = Order(
            client_name=d["client_name"],
            client_phone=d.get("client_phone"),
            client_email=d.get("client_email"),
            client_telegram_id=str(message.from_user.id),
            factory_name=factory.name,
            factory_email=factory.email,
            category=d["category"],
            model=d["model"],
            dimensions=d.get("dimensions"),
            material=d.get("material"),
            color=d.get("color"),
            configuration=d.get("configuration"),
            quantity=d.get("quantity", 1),
            delivery_date=d.get("delivery_date"),
            comments=d.get("comments"),
            photo_url=d.get("photo_url"),
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        order_id = order.id
    finally:
        db.close()

    await state.clear()
    await message.answer(
        f"✅ *Заявка №{order_id} успешно создана!*\n\n"
        "Ваша заявка принята и ожидает подтверждения администратора.\n\n"
        "Для новой заявки нажмите /order",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(Form.confirm, F.text == "❌ Начать заново")
async def step_restart(message: types.Message, state: FSMContext):
    await cmd_order(message, state)


@dp.message(Form.confirm)
async def step_confirm_invalid(message: types.Message, state: FSMContext):
    await message.answer(
        "Используйте кнопки ниже:",
        reply_markup=kb(["✅ Подтвердить и отправить"], ["❌ Начать заново"]),
    )


async def main():
    init_db()
    print("Бот запущен. Ctrl+C для остановки.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
