from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(300), nullable=False)
    display_name = Column(String(200))
    role = Column(String(20), default="manager")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)


class Factory(Base):
    __tablename__ = "factories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    email = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client_name = Column(String(200), nullable=False)
    client_phone = Column(String(50))
    client_email = Column(String(200))
    client_telegram_id = Column(String(50))

    factory_name = Column(String(200), nullable=False)
    factory_email = Column(String(200), nullable=False)

    category = Column(String(100), nullable=False)
    model = Column(String(200), nullable=False)
    dimensions = Column(String(100))
    material = Column(String(200))
    color = Column(String(200))
    configuration = Column(Text)
    quantity = Column(Integer, default=1)
    delivery_date = Column(String(100))
    comments = Column(Text)
    photo_url = Column(String(500))

    # Финансы
    order_amount = Column(Float)           # сумма заказа в рублях
    manager_id = Column(Integer)           # id менеджера из User
    manager_username = Column(String(100)) # логин менеджера

    status = Column(String(50), default="new")
    rejection_reason = Column(Text)
    sent_to_factory_at = Column(DateTime)
    factory_confirmed_at = Column(DateTime)
    confirmation_token = Column(String(36), unique=True)


class OrderAttachment(Base):
    __tablename__ = "order_attachments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, nullable=False)
    filename = Column(String(300), nullable=False)
    original_name = Column(String(300))
    uploaded_by = Column(String(100))
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class PriceBatch(Base):
    __tablename__ = "price_batches"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, nullable=False)
    factory_name = Column(String(200))
    filename = Column(String(300))
    item_count = Column(Integer, default=0)
    uploaded_by = Column(String(100))
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class PriceItem(Base):
    __tablename__ = "price_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_uuid = Column(String(36), nullable=False)
    article = Column(String(200))
    name = Column(String(500), nullable=False)
    category = Column(String(200))
    base_price = Column(Float, nullable=False)
    markup_price = Column(Float, nullable=False)  # base * 1.3


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False)
    role = Column(String(20))
    action = Column(String(500), nullable=False)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class SiteSettings(Base):
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True)
    theme = Column(String(20), default="light")
    primary_color = Column(String(20), default="indigo")


class OrderStatus:
    new = "new"
    sent_to_factory = "sent_to_factory"
    accepted = "accepted"
    rejected = "rejected"
