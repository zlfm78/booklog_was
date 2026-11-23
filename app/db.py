"""DB 연결. 주소와 계정은 모두 환경 변수로 받는다 (코드·이미지에 넣지 않음)."""
import os
from typing import Annotated

from fastapi import Depends
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def db_url() -> URL:
    # URL.create는 비밀번호의 특수 문자(@, / 등)를 알아서 처리한다. 문자열을 직접 이어 붙이지 않는다.
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT") or 5432),
        database=os.environ["DB_NAME"],
    )


engine = create_async_engine(
    db_url(),
    pool_size=int(os.environ.get("DB_POOL_SIZE") or 5),
    max_overflow=0,  # 풀 크기를 넘는 임시 연결 금지 → "Pod 수 × 풀 크기 ≤ max_connections"가 정확히 성립
    pool_pre_ping=True,  # DB Pod가 바뀐 뒤 끊긴 연결을 쓰기 전에 걸러냄
)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with Session() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
