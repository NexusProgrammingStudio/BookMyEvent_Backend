import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from .database import User, UserRole, get_session

# JWT config
ACCESS_SECRET_KEY = os.getenv("ACCESS_SECRET_KEY", "ILoveIndia")
REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY", "ILoveModi")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 180
REFRESH_TOKEN_EXPIRE_DAYS = 7

if not ACCESS_SECRET_KEY:
    raise AssertionError("Please Set Secret Key for Acccess Key Encryption")

if not REFRESH_SECRET_KEY:
    raise AssertionError("Please Set Secret Key for Refresh Key Encryption")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auto_login")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_current_user(
    token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User:
    # Decode JWT
    try:
        payload = jwt.decode(token, ACCESS_SECRET_KEY, algorithms=[ALGORITHM])  # type: ignore
        username: str = payload.get("sub")  # type: ignore
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # Fetch user from DB
    statement = select(User).where(User.username == username)
    user = session.exec(statement).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def authenticate_user(username: str, password: str, session: Session) -> User:
    statement = select(User).where(User.username == username)
    user = session.exec(statement).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return user


def create_access_token(
    data: dict,
    expires_delta: timedelta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, ACCESS_SECRET_KEY, algorithm=ALGORITHM)  # type: ignore


def create_refresh_token(
    data: dict, expires_delta: timedelta = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, REFRESH_SECRET_KEY, algorithm=ALGORITHM)  # type: ignore


def create_token(data: dict) -> dict:
    access_token = create_access_token(data)
    refresh_token = create_refresh_token(data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


def decode_refresh_token(token: str) -> str:
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])  # type: ignore
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return payload["sub"]


def organizer_required(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ORGANIZER:
        raise HTTPException(status_code=403, detail="Organizer access required")
    return current_user


def customer_required(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(status_code=403, detail="Customer access required")
    return current_user


def admin_required(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
