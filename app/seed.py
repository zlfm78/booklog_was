"""초기 데이터 넣기 (멱등): 없으면 넣고, 있으면 건드리지 않는다.

사용: python -m app.seed seed/catalog.yaml   (booklog_was 폴더에서)
데모 계정 비밀번호는 환경 변수 DEMO_PASSWORD (③④에서는 Secret)에서 받는다.
"""
import asyncio
import os
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import Session, engine
from app.models import Book, ReadingLog, User
from app.security import password_hash


async def seed(catalog_path: Path) -> None:
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))  # YAML의 2026-10-01은 date로 읽힘
    demo = catalog["demo_user"]
    username = demo["username"]
    demo_password = os.environ.get("DEMO_PASSWORD")
    if not demo_password or len(demo_password) < 8:
        sys.exit("DEMO_PASSWORD 환경 변수(8자 이상)가 필요합니다")

    async with Session() as session, session.begin():  # 한 트랜잭션: 중간에 실패하면 아무것도 남지 않음
        # ON CONFLICT DO NOTHING: 이미 있으면 그대로 둔다 → 사용자가 바꾼 정보·상태·평점·독후감·기록을 되돌리지 않음
        await session.execute(
            insert(User).values(username=username, name=demo["name"], nickname=demo["nickname"],
                                email=demo["email"].lower(), password_hash=password_hash.hash(demo_password))
            .on_conflict_do_nothing(index_elements=["username"])
        )
        user_id = await session.scalar(select(User.id).where(User.username == username))

        # RETURNING: 실제로 들어간 행만 돌려받아 개수를 센다 (여러 행 INSERT는 rowcount가 -1로 나올 수 있음)
        new_books = (await session.execute(
            insert(Book).values([{
                "user_id": user_id, "title": b["title"], "author": b["author"], "total_pages": b.get("total_pages"),
                "status": b["status"], "rating": b.get("rating"), "review": b.get("review"),
            } for b in catalog["books"]]).on_conflict_do_nothing(index_elements=["user_id", "title", "author"])
            .returning(Book.id)
        )).all()
        book_ids = {(t, a): i for i, t, a in await session.execute(
            select(Book.id, Book.title, Book.author).where(Book.user_id == user_id))}

        logs = [{"book_id": book_ids[(b["title"], b["author"])], "read_on": log["read_on"], "page": log["page"],
                 "note": log.get("note")} for b in catalog["books"] for log in b.get("logs", [])]
        new_logs = (await session.execute(
            insert(ReadingLog).values(logs).on_conflict_do_nothing(index_elements=["book_id", "read_on"])
            .returning(ReadingLog.id)
        )).all()
    await engine.dispose()
    print(f"seed ok: demo={username} books inserted={len(new_books)}/{len(catalog['books'])} "
          f"logs inserted={len(new_logs)}/{len(logs)} (기존 행은 유지)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("사용: python -m app.seed <catalog.yaml 경로>")
    asyncio.run(seed(Path(sys.argv[1])))
