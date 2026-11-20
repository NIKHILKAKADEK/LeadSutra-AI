from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from fastapi import HTTPException, Request, status
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.database.mongodb import get_mongo_collection

_password_hash = PasswordHash.recommended()


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def get_auth_secret() -> str:
    secret = get_settings().auth_jwt_secret
    if secret is None or len(secret.get_secret_value()) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not securely configured.",
        )
    return secret.get_secret_value()


def user_collection() -> Any:
    collection = get_mongo_collection("users")
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB is required for authentication.",
        )
    return collection


def public_user(document: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(document["_id"]),
        "name": document["name"],
        "email": document["email"],
    }


def create_session_cookie(
    response: Any, user: dict[str, Any], remember_me: bool
) -> None:
    lifetime = timedelta(days=30) if remember_me else timedelta(hours=12)
    expires_at = datetime.now(timezone.utc) + lifetime
    token = jwt.encode(
        {"sub": str(user["_id"]), "exp": expires_at},
        get_auth_secret(),
        algorithm="HS256",
    )
    response.set_cookie(
        key=get_settings().auth_cookie_name,
        value=token,
        max_age=int(lifetime.total_seconds()) if remember_me else None,
        httponly=True,
        secure=get_settings().auth_cookie_secure,
        samesite="lax",
        path="/api",
    )


def create_user(name: str, email: str, password: str) -> dict[str, Any]:
    collection = user_collection()
    normalized_email = email.strip().casefold()
    if collection.find_one({"email": normalized_email}, {"_id": 1}):
        raise AuthError(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = {
        "_id": str(uuid4()),
        "name": name.strip(),
        "email": normalized_email,
        "password_hash": _password_hash.hash(password),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        collection.insert_one(user)
    except Exception as exc:
        if getattr(exc, "code", None) != 11000:
            raise
        raise AuthError(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists.",
        ) from None
    return user


def authenticate_user(email: str, password: str) -> dict[str, Any]:
    collection = user_collection()
    user = collection.find_one({"email": email.strip().casefold()})
    if user is None or not _password_hash.verify(password, user.get("password_hash", "")):
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    return user


def get_current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(get_settings().auth_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = jwt.decode(token, get_auth_secret(), algorithms=["HS256"])
        user_id = claims.get("sub")
        if not isinstance(user_id, str):
            raise jwt.InvalidTokenError("Missing subject")
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    user = user_collection().find_one({"_id": user_id})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
