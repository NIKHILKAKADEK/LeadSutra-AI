from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from app.auth import (
    AuthError,
    authenticate_user,
    create_session_cookie,
    create_user,
    get_auth_secret,
    get_current_user,
    public_user,
)
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


class SignUpRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required.")
        return value.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class AuthResponse(BaseModel):
    user: dict[str, str]


def _handle_auth_error(error: AuthError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from None


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignUpRequest, response: Response) -> AuthResponse:
    get_auth_secret()
    try:
        user = create_user(payload.name, payload.email, payload.password)
    except AuthError as error:
        _handle_auth_error(error)
    create_session_cookie(response, user, remember_me=True)
    return AuthResponse(user=public_user(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response) -> AuthResponse:
    try:
        user = authenticate_user(payload.email, payload.password)
    except AuthError as error:
        _handle_auth_error(error)
    create_session_cookie(response, user, remember_me=payload.remember_me)
    return AuthResponse(user=public_user(user))


@router.get("/me", response_model=AuthResponse)
def current_user(user: Annotated[dict[str, Any], Depends(get_current_user)]) -> AuthResponse:
    return AuthResponse(user=public_user(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(
        key=get_settings().auth_cookie_name,
        httponly=True,
        secure=get_settings().auth_cookie_secure,
        samesite="lax",
        path="/api",
    )
