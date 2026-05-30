from __future__ import annotations

import datetime

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")
    morning_digest_time: Mapped[str] = mapped_column(String(5), default="09:00")
    evening_digest_time: Mapped[str] = mapped_column(String(5), default="19:00")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    channels: Mapped[list[Channel]] = relationship(back_populates="user", lazy="selectin")
    filters: Mapped[list[Filter]] = relationship(back_populates="user", lazy="selectin")


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    channel_username: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_title: Mapped[str | None] = mapped_column(String(500))
    channel_link: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="channels")
    posts: Mapped[list[Post]] = relationship(back_populates="channel", lazy="selectin")


class Filter(Base):
    __tablename__ = "filters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="filters")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    post_link: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    classification: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    channel: Mapped[Channel] = relationship(back_populates="posts")


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    period_start: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    period_end: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
