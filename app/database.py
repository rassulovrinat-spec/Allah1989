import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orders.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models import Base, Factory, User, SiteSettings
    from app.auth import hash_password

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Admin user from env (only on first run)
        if not db.query(User).filter(User.role == "admin").first():
            admin_username = os.getenv("ADMIN_USERNAME", "admin")
            admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
            db.add(User(
                username=admin_username,
                password_hash=hash_password(admin_password),
                display_name="Администратор",
                role="admin",
            ))

        # Sample factories
        if db.query(Factory).count() == 0:
            db.add_all([
                Factory(name="Фабрика №1", email="factory1@example.com"),
                Factory(name="МебельПром", email="factory2@example.com"),
                Factory(name="КорпусМебель", email="factory3@example.com"),
            ])

        # Default site settings
        if db.query(SiteSettings).count() == 0:
            db.add(SiteSettings())

        db.commit()
    finally:
        db.close()
