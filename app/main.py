import os
import socket

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app import books, users
from app.db import DbSession

# K8s에서 컨테이너 호스트 이름 = Pod 이름 (HOSTNAME 환경 변수와 같은 값)
POD = socket.gethostname()
NODE = os.environ.get("NODE_NAME", "-")  # ③④에서 Downward API(spec.nodeName)로 주입
VERSION = os.environ.get("APP_VERSION", "dev")  # ②부터 이미지 빌드 시 고정
REVISION = os.environ.get("APP_REVISION", "-")  # 1.1.0부터: 이미지를 빌드한 소스 커밋 (빌드 시 고정)

app = FastAPI(title="booklog-was", version=VERSION)


@app.middleware("http")
async def served_by(request, call_next):
    # 어느 Pod·어느 버전이 응답했는지 모든 응답에 표시 (로드밸런싱·롤링 업데이트 확인용)
    response = await call_next(request)
    response.headers["X-Served-By"] = POD
    response.headers["X-App-Version"] = VERSION
    return response


@app.get("/api/health/live")
async def live():
    # DB를 보지 않는다: DB 장애 때 was까지 재시작되는 연쇄 장애 방지
    return {"status": "ok"}


@app.get("/api/health/ready")
async def ready(session: DbSession):
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "db unavailable")
    return {"status": "ok"}


@app.get("/api/info")
async def info():
    return {"pod": POD, "node": NODE, "version": VERSION, "revision": REVISION}


app.include_router(users.router)
app.include_router(books.router)
