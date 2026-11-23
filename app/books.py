"""내 책과 독서 기록. 모든 경로가 로그인(CurrentUser)을 요구하고, 항상 user_id 조건을 붙여 자기 것만 다룬다.
다른 사용자의 책·기록은 404 (존재 여부를 알려 주지 않음)."""
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.db import DbSession
from app.models import Book, ReadingLog
from app.security import CurrentUser

router = APIRouter(prefix="/api/books")

Status = Literal["unread", "reading", "done"]
Rating = Annotated[int, Field(ge=1, le=5)]
Pages = Annotated[int, Field(ge=1, le=100_000)]
Text = Annotated[str, Field(max_length=10_000)]
NOT_FOUND = "책이 없습니다"


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=100)
    total_pages: Pages | None = None


class BookPatch(BaseModel):
    # 보낸 필드만 바꾼다. rating/review/total_pages에 null을 보내면 지움
    status: Status | None = None
    rating: Rating | None = None
    review: Text | None = None
    total_pages: Pages | None = None


class LogIn(BaseModel):
    page: int = Field(ge=0, le=100_000)
    note: Text | None = None


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    author: str
    total_pages: int | None
    status: Status
    rating: int | None
    review: str | None
    created_at: datetime
    updated_at: datetime


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    read_on: date
    page: int
    note: str | None
    created_at: datetime
    updated_at: datetime


class Progress(BaseModel):
    page: int
    percent: int | None  # total_pages가 없으면 None


class BookDetail(BookOut):
    progress: Progress | None  # 기록이 없으면 None
    logs: list[LogOut]  # 최근 날짜순


class BookPage(BaseModel):
    items: list[BookOut]
    total: int
    page: int
    size: int


async def my_book(session, book_id: int, user_id: int, lock: bool = False) -> Book:
    stmt = select(Book).where(Book.id == book_id, Book.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()  # 기록 저장 중 같은 책의 상태를 다른 요청이 동시에 바꾸지 못하게 행 잠금
    book = await session.scalar(stmt)
    if book is None:
        raise HTTPException(404, NOT_FOUND)
    return book


async def my_logs(session, book_id: int, user_id: int) -> list[ReadingLog]:
    # JOIN으로 "이 책이 내 책인가"를 같은 쿼리에서 확인: 남의 책 id면 빈 목록
    rows = await session.scalars(
        select(ReadingLog).join(Book, Book.id == ReadingLog.book_id)
        .where(Book.id == book_id, Book.user_id == user_id)
        .order_by(ReadingLog.read_on.desc())
    )
    return list(rows)


async def detail(session, book_id: int, user_id: int) -> BookDetail:
    session.expunge_all()  # 같은 요청에서 바뀐 값(updated_at, status)을 DB에서 새로 읽음
    book = await my_book(session, book_id, user_id)
    logs = await my_logs(session, book_id, user_id)
    progress = None
    if logs:
        page = logs[0].page  # 가장 최근 날짜의 쪽
        percent = min(100, page * 100 // book.total_pages) if book.total_pages else None
        progress = Progress(page=page, percent=percent)
    return BookDetail(**BookOut.model_validate(book).model_dump(), progress=progress,
                      logs=[LogOut.model_validate(log) for log in logs])


@router.get("", response_model=BookPage)
async def list_books(
    user: CurrentUser,
    session: DbSession,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Status | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 10,
):
    where = [Book.user_id == user.id]
    if q:
        pattern = f"%{q}%"  # 바인딩 파라미터로 전달되므로 SQL 주입 없음
        where.append(or_(Book.title.ilike(pattern), Book.author.ilike(pattern)))
    if status:
        where.append(Book.status == status)
    total = await session.scalar(select(func.count()).select_from(Book).where(*where))
    rows = await session.scalars(
        select(Book).where(*where).order_by(Book.updated_at.desc(), Book.id.desc())
        .offset((page - 1) * size).limit(size)
    )
    return BookPage(items=rows.all(), total=total, page=page, size=size)


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(book_id: int, user: CurrentUser, session: DbSession):
    return await detail(session, book_id, user.id)


@router.post("", response_model=BookDetail, status_code=201)
async def create_book(body: BookIn, user: CurrentUser, session: DbSession):
    book = Book(user_id=user.id, **body.model_dump())
    session.add(book)
    try:
        await session.commit()
    except IntegrityError:  # (user_id, title, author) UNIQUE 위반
        raise HTTPException(409, "같은 제목·저자의 책이 이미 있습니다")
    return await detail(session, book.id, user.id)


@router.patch("/{book_id}", response_model=BookDetail)
async def update_book(book_id: int, body: BookPatch, user: CurrentUser, session: DbSession):
    values = body.model_dump(exclude_unset=True)
    if values.get("status", "") is None:
        raise HTTPException(422, "status는 null일 수 없습니다")
    if not values:
        raise HTTPException(400, "바꿀 값(status, rating, review, total_pages)이 없습니다")
    await my_book(session, book_id, user.id, lock=True)
    if values.get("total_pages"):
        max_page = await session.scalar(select(func.max(ReadingLog.page)).where(ReadingLog.book_id == book_id))
        if max_page is not None and max_page > values["total_pages"]:
            raise HTTPException(422, f"이미 {max_page}쪽까지 기록되어 있어 전체 쪽수를 그보다 작게 할 수 없습니다")
    await session.execute(update(Book).where(Book.id == book_id).values(**values))  # updated_at 자동 갱신
    await session.commit()
    return await detail(session, book_id, user.id)


@router.delete("/{book_id}", status_code=204)
async def delete_book(book_id: int, user: CurrentUser, session: DbSession):
    # 기록은 reading_logs.book_id의 ON DELETE CASCADE가 함께 지운다. CASCADE가 없으면 이 문장이 FK 위반으로 실패함
    result = await session.execute(delete(Book).where(Book.id == book_id, Book.user_id == user.id))
    if result.rowcount == 0:
        raise HTTPException(404, NOT_FOUND)
    await session.commit()


@router.get("/{book_id}/logs", response_model=list[LogOut])
async def list_logs(book_id: int, user: CurrentUser, session: DbSession):
    await my_book(session, book_id, user.id)  # 남의 책이면 빈 목록이 아니라 404
    return await my_logs(session, book_id, user.id)


@router.put("/{book_id}/logs/{read_on}", response_model=BookDetail)
async def save_log(book_id: int, read_on: date, body: LogIn, user: CurrentUser, session: DbSession):
    """그날의 기록을 저장한다. 같은 날짜가 있으면 덮어쓴다(upsert).
    기록 저장과 책 상태 변경을 한 트랜잭션으로: 둘 중 하나만 반영되는 일이 없다."""
    book = await my_book(session, book_id, user.id, lock=True)
    if book.total_pages and body.page > book.total_pages:
        raise HTTPException(422, f"쪽수는 전체 쪽수({book.total_pages}) 이하여야 합니다")

    stmt = insert(ReadingLog).values(book_id=book_id, read_on=read_on, page=body.page, note=body.note)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=["book_id", "read_on"],
        set_={"page": stmt.excluded.page, "note": stmt.excluded.note, "updated_at": func.now()},
    ))

    # 자동 상태: 다 읽었으면 done, 처음 기록이면 unread → reading. 아니면 그대로(수동 변경 존중)
    status = book.status
    if book.total_pages and body.page >= book.total_pages:
        status = "done"
    elif status == "unread":
        status = "reading"
    # 상태가 같아도 updated_at을 갱신 → 목록(최근 수정순)에서 방금 읽은 책이 위로
    await session.execute(update(Book).where(Book.id == book_id).values(status=status, updated_at=func.now()))
    await session.commit()
    return await detail(session, book_id, user.id)


@router.delete("/{book_id}/logs/{read_on}", response_model=BookDetail)
async def delete_log(book_id: int, read_on: date, user: CurrentUser, session: DbSession):
    """그날의 기록을 지운다. 책 상태는 되돌리지 않는다(자동 변경은 앞으로 가는 방향만).
    진행률은 detail()이 남은 기록 중 가장 최근 날짜로 다시 계산한다."""
    await my_book(session, book_id, user.id, lock=True)
    result = await session.execute(
        delete(ReadingLog).where(ReadingLog.book_id == book_id, ReadingLog.read_on == read_on)
    )
    if result.rowcount == 0:
        raise HTTPException(404, "그 날짜의 기록이 없습니다")
    await session.execute(update(Book).where(Book.id == book_id).values(updated_at=func.now()))
    await session.commit()
    return await detail(session, book_id, user.id)
