import os
from sqlalchemy import create_engine, text
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


def _migrate():
    """Add missing columns to existing tables without losing data."""
    if "sqlite" not in DATABASE_URL:
        return
    db_path = DATABASE_URL.replace("sqlite:///", "").lstrip("./")
    if not os.path.exists(db_path):
        return
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    def add_col(table, col, col_type):
        cur.execute(f"PRAGMA table_info({table})")
        existing = [r[1] for r in cur.fetchall()]
        if col not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")

    add_col("orders", "order_amount", "REAL")
    add_col("orders", "manager_id", "INTEGER")
    add_col("orders", "manager_username", "TEXT")

    conn.commit()
    conn.close()


def init_db():
    from app.models import Base, Factory, User, SiteSettings
    from app.auth import hash_password

    _migrate()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.role == "admin").first():
            admin_username = os.getenv("ADMIN_USERNAME", "admin")
            admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
            db.add(User(
                username=admin_username,
                password_hash=hash_password(admin_password),
                display_name="Администратор",
                role="admin",
            ))

        if db.query(Factory).count() == 0:
            db.add_all([
                Factory(name="Фабрика №1", email="factory1@example.com"),
                Factory(name="МебельПром", email="factory2@example.com"),
                Factory(name="КорпусМебель", email="factory3@example.com"),
            ])

        if db.query(SiteSettings).count() == 0:
            db.add(SiteSettings())

        db.commit()
    finally:
        db.close()
