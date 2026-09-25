import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import cfg


class Base(DeclarativeBase):
    pass


class DB:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite"):
            Path(url.split("///")[-1]).parent.mkdir(parents=True, exist_ok=True)
            connect_args = {"check_same_thread": False}
        else:
            connect_args = {}
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=cfg.db.pool_size,
            pool_timeout=cfg.db.pool_timeout,
            connect_args=connect_args,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def create_all(self) -> None:
        from app.db import models  # noqa: F401

        Base.metadata.create_all(self.engine)

    def session(self):
        return self.SessionLocal()

    async def run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)


def build_db(url: str) -> DB | None:
    if not url:
        return None
    return DB(url)