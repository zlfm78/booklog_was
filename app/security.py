"""비밀번호(Argon2)와 로그인 토큰(JWT, HttpOnly 쿠키). 서버는 세션을 저장하지 않는다(무상태)."""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException
from pwdlib import PasswordHash

from app.db import DbSession
from app.models import User

password_hash = PasswordHash.recommended()  # pwdlib 권장 = Argon2

# 모든 was 파드가 같은 키를 써야 다른 파드가 발급한 토큰도 검증된다 → ③④에서는 Secret으로 주입.
# 키가 없으면 프로세스마다 다른 임의 키를 만든다: 요청이 다른 파드로 가면 로그인이 풀린다 (시연용)
JWT_SECRET = os.environ.get("JWT_SECRET") or ""
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(32)
    logging.getLogger("uvicorn.error").warning(
        "!!! JWT_SECRET 없음: 이 프로세스만 아는 임의 키 사용. 다른 프로세스·파드와 로그인이 공유되지 않습니다 !!!")
TOKEN_TTL = timedelta(minutes=int(os.environ.get("JWT_EXPIRE_MINUTES") or 60))
COOKIE_NAME = "access_token"


def make_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + TOKEN_TTL
    return jwt.encode({"sub": str(user_id), "exp": exp}, JWT_SECRET, algorithm="HS256")


async def current_user(session: DbSession, access_token: Annotated[str | None, Cookie()] = None) -> User:
    if not access_token:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        # algorithms를 고정해야 'alg: none' 같은 위조 토큰을 거부한다. exp(만료)와 서명도 여기서 검사된다.
        user_id = int(jwt.decode(access_token, JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "로그인이 만료되었거나 올바르지 않습니다")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(401, "사용자가 없습니다")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
