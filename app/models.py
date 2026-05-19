from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(300), nullable=False)
    display_name = Column(String(200))
    role = Column(String(20), default="manager")  # admin / manager
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

    status = Column(String(50), default="new")
    rejection_reason = Column(Text)
    sent_to_factory_at = Column(DateTime)
    factory_confirmed_at = Column(DateTime)
    confirmation_token = Column(String(36), unique=True)


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
