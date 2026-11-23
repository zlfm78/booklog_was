"""테이블 3개: users 1─N books 1─N reading_logs. 사용자는 자기 책과 그 기록만 본다."""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, MetaData, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

STATUSES = ("unread", "reading", "done")  # 화면: 읽지 않음 / 읽는 중 / 다 읽음


class Base(DeclarativeBase):
    # 제약 조건 이름 규칙: 마이그레이션 파일과 모델의 이름이 항상 같아진다
    metadata = MetaData(naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    })


def created_at():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(20), unique=True)  # 아이디(로그인 ID). 가입 후 바꾸지 않음
    password_hash: Mapped[str] = mapped_column(String(255))  # Argon2 해시만 저장 (원문 비밀번호는 저장하지 않음)
    name: Mapped[str] = mapped_column(String(50))  # 이름
    nickname: Mapped[str] = mapped_column(String(20))  # 닉네임 (화면 표시용, 중복 허용)
    email: Mapped[str] = mapped_column(String(255), unique=True)  # 연락처 (로그인에는 쓰지 않음)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("user_id", "title", "author"),  # 시드의 "없으면 넣기" 기준
        CheckConstraint(f"status IN {STATUSES}", name="status"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),  # NULL(평점 없음)은 통과
        CheckConstraint("total_pages > 0", name="total_pages"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(100))
    total_pages: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(10), server_default="unread")
    rating: Mapped[int | None]
    review: Mapped[str | None] = mapped_column(Text)  # 독후감 (책마다 1개)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ReadingLog(Base):
    __tablename__ = "reading_logs"
    __table_args__ = (
        UniqueConstraint("book_id", "read_on"),  # 책·날짜당 1개 → 같은 날 다시 기록하면 덮어씀
        CheckConstraint("page >= 0", name="page"),  # page ≤ total_pages는 다른 테이블 값이라 앱에서 검사
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    read_on: Mapped[date] = mapped_column(Date)
    page: Mapped[int]  # 그날 마지막으로 읽은 쪽
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
