"""alembic upgrade head 실행 환경.

③④에서는 was Pod마다 initContainer가 이 마이그레이션을 실행한다. Pod 2개가 동시에 시작하면
같은 테이블을 두 번 만들려다 실패할 수 있으므로, PostgreSQL advisory lock으로 한 번에 하나만 실행한다.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from app.db import db_url
from app.models import Base

# 임의의 고정 정수. 같은 숫자로 잠그는 프로세스끼리만 서로 기다린다.
MIGRATION_LOCK_ID = 7_420_001

fileConfig(context.config.config_file_name)


def run_migrations_online() -> None:
    # 마이그레이션은 한 번만 도는 작업이라 동기 엔진으로 충분 (psycopg 3은 동기·비동기 모두 지원)
    engine = create_engine(db_url())
    with engine.connect() as connection:
        # 세션 수준 잠금: 다른 프로세스가 잡고 있으면 풀릴 때까지 대기.
        # 프로세스가 죽어 연결이 끊기면 PostgreSQL이 잠금을 자동으로 푼다.
        connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        connection.commit()  # 잠금은 유지된 채 트랜잭션만 끝냄 → 아래 마이그레이션이 자기 트랜잭션으로 커밋됨
        try:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()  # 기다린 쪽은 여기서 "이미 head"임을 확인하고 아무것도 하지 않음
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
            connection.commit()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline 모드는 사용하지 않습니다")
run_migrations_online()
