"""DB 연결. 주소와 계정은 모두 환경 변수로 받는다 (코드·이미지에 넣지 않음).

DB_IAM_AUTH=true (④ RDS Proxy): 비밀번호 대신 IAM 인증 토큰으로 접속한다.
  - 토큰은 연결을 새로 맺을 때마다 만든다 (유효 15분, 이미 맺은 연결은 만료와 상관없이 유지)
  - 자격 증명은 EKS Pod Identity가 주입한 환경 변수로 boto3가 찾는다 (코드에 키 없음)
  - 토큰은 TLS 연결에서만 쓴다 → PGSSLMODE · PGSSLROOTCERT(libpq 환경 변수)로 지정
"""
import os
from typing import Annotated

from fastapi import Depends
from sqlalchemy import URL, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


IAM_AUTH = os.environ.get("DB_IAM_AUTH") == "true"


def db_url() -> URL:
    # URL.create는 비밀번호의 특수 문자(@, / 등)를 알아서 처리한다. 문자열을 직접 이어 붙이지 않는다.
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=None if IAM_AUTH else os.environ["DB_PASSWORD"],
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

if IAM_AUTH:
    import boto3  # IAM 인증을 쓸 때만 필요 (①②③에서는 불러오지 않음)

    _rds = boto3.client("rds", region_name=os.environ["AWS_REGION"])

    @event.listens_for(engine.sync_engine, "do_connect")
    def _iam_token(dialect, conn_rec, cargs, cparams):
        # 서명만 하는 계산이라 AWS API를 호출하지 않는다 (자격 증명은 boto3가 캐시 · 갱신)
        cparams["password"] = _rds.generate_db_auth_token(
            DBHostname=cparams["host"], Port=int(cparams.get("port") or 5432), DBUsername=cparams["user"]
        )

Session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with Session() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
