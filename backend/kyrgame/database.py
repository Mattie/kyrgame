import os
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/kyrgame"
DEFAULT_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DEFAULT_POOL_MAX_OVERFLOW = int(os.getenv("DB_POOL_MAX_OVERFLOW", "10"))
DEFAULT_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))


def get_engine(database_url: Optional[str] = None, **engine_kwargs):
    url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    pooled_kwargs = {
        "pool_size": DEFAULT_POOL_SIZE,
        "max_overflow": DEFAULT_POOL_MAX_OVERFLOW,
        "pool_recycle": DEFAULT_POOL_RECYCLE,
        "pool_pre_ping": True,
    }

    if url.startswith("sqlite"):
        pooled_kwargs.pop("pool_size", None)
        pooled_kwargs.pop("max_overflow", None)
        pooled_kwargs.pop("pool_recycle", None)
        pooled_kwargs.setdefault("connect_args", {"check_same_thread": False})

    pooled_kwargs.update(engine_kwargs)
    return create_engine(url, future=True, **pooled_kwargs)


def init_db_schema(engine):
    Base.metadata.create_all(engine)


def create_session_factory(engine):
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
    )


def create_session(engine):
    session_factory = create_session_factory(engine)
    return session_factory()


def _default_alembic_config() -> Path:
    return Path(__file__).resolve().parents[1] / "alembic.ini"


def run_migrations(
    database_url: Optional[str] = None,
    config_path: Optional[Path] = None,
    revision: str = "head",
    engine=None,
):
    config = Config(str(config_path or _default_alembic_config()))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    if engine is not None:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    else:
        command.upgrade(config, revision)
