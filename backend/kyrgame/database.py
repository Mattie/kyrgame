from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base


def get_engine(database_url: str = "sqlite:///kyrgame.db"):
    return create_engine(database_url, future=True)


def init_db_schema(engine):
    Base.metadata.create_all(engine)


def create_session(engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()
