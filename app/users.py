"""회원: 가입, 로그인(HttpOnly 쿠키 발급), 로그아웃, 내 정보 조회·수정, 비밀번호 변경, 탈퇴.
아이디(username)는 로그인 ID라 바꾸지 않는다. 이메일은 연락처(유니크)이고 로그인에는 쓰지 않는다."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.db import DbSession
from app.models import User
from app.security import COOKIE_NAME, TOKEN_TTL, CurrentUser, make_token, password_hash

router = APIRouter(prefix="/api/auth")

Username = Annotated[str, Field(pattern=r"^[a-z0-9_]{4,20}$")]  # 영문 소문자·숫자·_ 4~20자
Password = Annotated[str, Field(min_length=8, max_length=128)]
Name = Annotated[str, Field(min_length=1, max_length=50)]
Nickname = Annotated[str, Field(min_length=2, max_length=20)]
Email = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)]


class RegisterIn(BaseModel):
    username: Username
    password: Password
    name: Name
    nickname: Nickname
    email: Email


class LoginIn(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=128)


class ProfilePatch(BaseModel):
    # 보낸 필드만 바꾼다. 셋 다 필수 항목이라 null로 지울 수는 없다
    name: Name | None = None
    nickname: Nickname | None = None
    email: Email | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: Password


class PasswordIn(BaseModel):
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    # password_hash는 내보내지 않는다
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    nickname: str
    email: str


def set_login_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_token(user_id),
        max_age=int(TOKEN_TTL.total_seconds()),
        httponly=True,  # JavaScript(document.cookie)로 읽을 수 없음 → XSS로 토큰을 훔치기 어려움
        samesite="lax",  # 다른 사이트에서 보내는 POST 등에는 쿠키를 싣지 않음 → CSRF 완화
        # shortcut: secure 없음 (③은 HTTP라 Secure 쿠키가 전송되지 않음). HTTPS를 붙이면 secure=True
    )


def conflict_message(e: IntegrityError) -> str:
    # 어느 UNIQUE 제약에 걸렸는지 제약 이름으로 구분 (models.py의 naming_convention이 정한 이름)
    constraint = getattr(getattr(e.orig, "diag", None), "constraint_name", "")
    return "이미 사용 중인 아이디입니다" if constraint == "uq_users_username" else "이미 사용 중인 이메일입니다"


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, session: DbSession):
    user = User(username=body.username, name=body.name, nickname=body.nickname, email=body.email.lower(),
                password_hash=password_hash.hash(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as e:  # username 또는 email UNIQUE 위반
        raise HTTPException(409, conflict_message(e))
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, response: Response, session: DbSession):
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not password_hash.verify(body.password, user.password_hash):
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")  # 어느 쪽이 틀렸는지 알려 주지 않음
    set_login_cookie(response, user.id)
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    # 서버에 세션이 없으므로 "로그아웃" = 브라우저의 쿠키 삭제. 토큰 자체는 만료 시각까지 유효함 (무상태의 한계)
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(body: ProfilePatch, user: CurrentUser, session: DbSession):
    values = body.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()):
        raise HTTPException(422, "이름·닉네임·이메일은 비울 수 없습니다")
    if not values:
        raise HTTPException(400, "바꿀 값(name, nickname, email)이 없습니다")
    if "email" in values:
        values["email"] = values["email"].lower()
    try:
        await session.execute(update(User).where(User.id == user.id).values(**values))  # updated_at 자동 갱신
        await session.commit()
    except IntegrityError:  # 다른 사용자가 쓰는 email
        raise HTTPException(409, "이미 사용 중인 이메일입니다")
    return await session.get(User, user.id, populate_existing=True)


@router.put("/me/password", status_code=204)
async def change_password(body: PasswordChange, user: CurrentUser, response: Response, session: DbSession):
    if not password_hash.verify(body.current_password, user.password_hash):
        raise HTTPException(401, "현재 비밀번호가 올바르지 않습니다")
    await session.execute(
        update(User).where(User.id == user.id).values(password_hash=password_hash.hash(body.new_password))
    )
    await session.commit()
    # 지금 브라우저에는 새 토큰을 발급. 다른 기기에 이미 발급된 JWT는 만료 전까지 유효 (무상태의 한계, 문서에 기록)
    set_login_cookie(response, user.id)


@router.delete("/me", status_code=204)
async def withdraw(body: PasswordIn, user: CurrentUser, response: Response, session: DbSession):
    # 쿠키만으로는 탈퇴시키지 않는다: 자리를 비운 사이 누가 누르는 경우를 막으려고 비밀번호를 다시 확인
    if not password_hash.verify(body.password, user.password_hash):
        raise HTTPException(401, "비밀번호가 올바르지 않습니다")
    # 책·기록은 DB의 ON DELETE CASCADE가 함께 지운다 (앱이 자식 행을 따로 지우지 않음)
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    # 이미 발급된 JWT는 서명상 만료 전까지 유효하지만, current_user가 요청마다 DB에서 사용자를 찾으므로 401이 된다
    response.delete_cookie(COOKIE_NAME)
