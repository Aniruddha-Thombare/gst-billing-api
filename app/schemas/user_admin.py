from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

AssignableRole = Literal["accountant", "viewer", "auditor"]


def _check_password_strength(value: str) -> str:
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        raise ValueError("Password must contain at least one letter and one digit.")
    return value


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=72)
    role: AssignableRole

    _strength = field_validator("password")(_check_password_strength)


class UserRoleUpdateRequest(BaseModel):
    role: AssignableRole


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)

    _strength = field_validator("new_password")(_check_password_strength)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool