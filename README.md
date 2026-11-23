# booklog_was

**booklog**(개인 서재 · 독서 기록장)의 **was** — JSON API 서버입니다.
회원 가입 · 로그인(JWT HttpOnly 쿠키), 내 책 등록 · 조회 · 수정 · 삭제, 날짜별 독서 기록, 독후감을 처리하고 데이터는 PostgreSQL에만 저장합니다.

| 저장소 | 역할 |
|---|---|
| **booklog_was** (이 저장소) | API 소스 → 이미지 `booklog-was` |
| [booklog_web](https://github.com/zlfm78/booklog_web) | 화면(React) → 이미지 `booklog-web` |
| [booklog_infra](https://github.com/zlfm78/booklog_infra) | 실행 · 배포 구성(compose, Kubernetes), 테스트 시나리오, 문서 |

## 기술 스택

Python 3.12 · FastAPI · SQLAlchemy 2.0(async) + psycopg 3 · Alembic · uvicorn · PyJWT + pwdlib(Argon2). 버전은 `requirements.txt`에 고정.

## 구성

```
app/
├── main.py       앱 생성, 헬스 체크(/api/health/*), /api/info, 응답 헤더
├── db.py         DB 연결 (주소 · 계정은 환경 변수), 연결 풀
├── models.py     테이블 3개: users 1─N books 1─N reading_logs
├── security.py   비밀번호 해시(Argon2), JWT 발급 · 검증
├── users.py      /api/auth/*  회원
├── books.py      /api/books/* 책 · 독서 기록
└── seed.py       초기 데이터 (멱등)
migrations/       Alembic 마이그레이션
seed/catalog.yaml 데모 계정 + 책 10권
```

## 환경 변수

코드와 이미지에는 값을 넣지 않고 실행할 때 환경 변수로 받습니다. 키 목록과 예시 파일은 [booklog_infra의 `.env.example`](https://github.com/zlfm78/booklog_infra/blob/main/.env.example)에 있습니다.

| 구분 | 키 |
|---|---|
| 일반 설정 | `DB_HOST` `DB_PORT` `DB_NAME` `DB_POOL_SIZE` `JWT_EXPIRE_MINUTES` `APP_VERSION` |
| 비밀 | `DB_USER` `DB_PASSWORD` `JWT_SECRET` `DEMO_PASSWORD` |

DB 계정은 둘로 나눕니다. was는 **앱 계정**(슈퍼유저 아님, 테이블 읽기 · 쓰기만)으로 접속하고, 테이블을 만드는 마이그레이션 단계만 **관리 계정**으로 접속합니다.

```bash
# 마이그레이션 단계 (DB_USER · DB_PASSWORD = 관리 계정, APP_DB_USER · APP_DB_PASSWORD = 앱 계정)
alembic upgrade head                   # 테이블 생성 (관리 계정 소유)
python -m app.dbrole                   # 앱 계정 생성 · 권한 부여 (멱등)
python -m app.seed seed/catalog.yaml   # 초기 데이터
```

## 로컬 실행 (WSL 2 Ubuntu, ①)

DB(`postgres:18.7` 컨테이너)를 먼저 띄운 뒤 실행합니다.

```bash
cd ~/booklog/booklog_was && set -a && . ../booklog_infra/.env && set +a
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                   # 테이블 생성
python -m app.seed seed/catalog.yaml   # 초기 데이터 (다시 실행해도 결과 같음)
uvicorn app.main:app --port 8000
```

## API 요약

| 구분 | 경로 |
|---|---|
| 운영 | `GET /api/health/live`(프로세스), `GET /api/health/ready`(DB 연결 `SELECT 1`), `GET /api/info` |
| 회원 | `POST /api/auth/register` · `login` · `logout`, `GET · PATCH · DELETE /api/auth/me`, `PUT /api/auth/me/password` |
| 책 | `POST · GET /api/books`(검색 `q`, 상태 `status`), `GET · PATCH · DELETE /api/books/{id}` |
| 독서 기록 | `GET /api/books/{id}/logs`, `PUT · DELETE /api/books/{id}/logs/{YYYY-MM-DD}` |

로그인이 없으면 401, 다른 사용자의 책 · 기록은 404. was를 직접 연 주소의 `/docs`(FastAPI 자동 문서, 예: `http://localhost:8000/docs`)에서 요청 · 응답 형식을 볼 수 있습니다.

## 버전

Git 태그와 이미지 태그를 맞춥니다: `v1.0.0` = `booklog-was:1.0.0`.
