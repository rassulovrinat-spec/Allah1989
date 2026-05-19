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
    from app.models import Base, Factory
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Factory).count() == 0:
            db.add_all([
                Factory(name="Фабрика №1", email="factory1@example.com"),
                Factory(name="МебельПром", email="factory2@example.com"),
                Factory(name="КорпусМебель", email="factory3@example.com"),
            ])
            db.commit()
    finally:
        db.close()
