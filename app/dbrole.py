"""앱 전용 DB 계정 만들기 (멱등). migrate 단계에서 관리 계정으로 실행한다.

사용: python -m app.dbrole
  DB_HOST · DB_PORT · DB_NAME · DB_USER · DB_PASSWORD  = 관리 계정 (테이블을 만들고 소유하는 계정)
  APP_DB_USER · APP_DB_PASSWORD                       = was가 접속할 앱 계정

was는 슈퍼유저가 아니라 이 앱 계정으로 접속한다 (최소 권한):
  - 할 수 있는 것: 테이블 행 읽기 · 쓰기 · 수정 · 삭제, 시퀀스로 id 받기
  - 못 하는 것: 테이블 만들기 · 바꾸기 · 지우기, 다른 계정 · DB 만들기 (DDL은 migrate가 관리 계정으로)
계정이 없으면 만들고, 있으면 비밀번호와 권한을 다시 맞춘다 → 여러 번 실행해도 결과가 같다.
postgres 이미지의 init 스크립트(빈 볼륨에서만 실행)가 아니라 여기서 만드는 이유: 기존 볼륨 · RDS에서도 같은 방법으로 동작.
"""
import os

import psycopg
from psycopg import sql

# migrations/env.py의 잠금(7_420_001)과 다른 고정 정수. was Pod 여러 개의 migrate가 동시에 돌아도 한 번에 하나만
ROLE_LOCK_ID = 7_420_002


def main() -> None:
    admin = os.environ["DB_USER"]
    app_user = os.environ["APP_DB_USER"]
    app_password = os.environ["APP_DB_PASSWORD"]
    dbname = os.environ["DB_NAME"]
    if app_user == admin:
        raise SystemExit("APP_DB_USER는 관리 계정(DB_USER)과 달라야 합니다")

    with psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT") or 5432),
        dbname=dbname,
        user=admin,
        password=os.environ["DB_PASSWORD"],
        autocommit=True,
    ) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (ROLE_LOCK_ID,))
        try:
            role = sql.Identifier(app_user)
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,)).fetchone()
            # 비밀번호는 sql.Literal로 안전하게 따옴표 처리 (DDL은 %s 바인딩을 못 씀). 서버가 scram-sha-256으로 해시해 저장
            conn.execute(
                sql.SQL("{} ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(
                    sql.SQL("ALTER" if exists else "CREATE"), role, sql.Literal(app_password)
                )
            )
            for stmt in (
                "GRANT CONNECT ON DATABASE {db} TO {role}",
                "GRANT USAGE ON SCHEMA public TO {role}",
                # 지금 있는 테이블 · 시퀀스
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
                # 앞으로 관리 계정이 만들 테이블 · 시퀀스 (다음 마이그레이션)에도 같은 권한이 자동으로 붙음
                "ALTER DEFAULT PRIVILEGES FOR ROLE {admin} IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
                "ALTER DEFAULT PRIVILEGES FOR ROLE {admin} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {role}",
            ):
                conn.execute(sql.SQL(stmt).format(db=sql.Identifier(dbname), role=role, admin=sql.Identifier(admin)))
            # 마이그레이션 기록표는 앱이 건드릴 이유가 없다
            if conn.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0]:
                conn.execute(sql.SQL("REVOKE ALL ON public.alembic_version FROM {}").format(role))
            superuser = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (app_user,)).fetchone()[0]
            print(f"db role ok: app={app_user} {'updated' if exists else 'created'} superuser={superuser}")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ROLE_LOCK_ID,))


if __name__ == "__main__":
    main()
