# booklog-was 이미지 (최적화 적용. 기준선과 비교: booklog_infra 문서 ② 빌드 최적화)

# 베이스: Python 3.12 slim (빌드 도구 · 문서 등을 뺀 Debian). 의존성이 모두 바이너리 wheel이라 컴파일러가 필요 없다
FROM python:3.12-slim

# .pyc 파일을 쓰지 않고(읽기 전용 소스), 로그를 버퍼 없이 바로 출력
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) 의존성만 먼저: requirements.txt가 그대로면 아래 설치 레이어를 캐시에서 재사용 (소스만 바뀐 재빌드가 빠름)
COPY requirements.txt .
# --no-cache-dir: pip 다운로드 캐시를 이미지에 남기지 않음
RUN pip install --no-cache-dir -r requirements.txt

# 실행 전용 사용자 (root 아님). UID를 숫자로 고정 → K8s runAsNonRoot가 숫자로 확인할 수 있음
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

# 2) 자주 바뀌는 소스는 마지막에. 마이그레이션 · 시드도 포함 (같은 이미지로 alembic · seed 실행)
#    파일 소유자는 root 그대로 → 실행 사용자는 읽기만 가능
COPY alembic.ini ./
COPY migrations ./migrations
COPY seed ./seed
COPY app ./app

# 빌드할 때 고정하는 값: 버전(화면 · /api/info), 소스 커밋 (docker build --build-arg ...)
ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.title="booklog-was" \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.source="https://github.com/zlfm78/booklog_was"

USER 10001
EXPOSE 8000

# exec 형식: uvicorn이 PID 1이 되어 종료 신호(SIGTERM)를 직접 받음. 0.0.0.0: 컨테이너 밖 요청 수신
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
