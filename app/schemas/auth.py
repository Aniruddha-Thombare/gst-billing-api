import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

from app.models.enum import UserRole


# Password: at least one lowercase, one uppercase, one digit and one special
# character, 8-72 characters total. Max 72 because bcrypt only uses the first
# 72 bytes, so longer passwords would give a false sense of strength.
_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,72}$"
)

# Text that is trimmed of leading/trailing spaces before length checks run.
_TrimmedName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]


class TenantRegisterRequest(BaseModel):
    """
    Used by: POST /auth/register

    Creates a Tenant, its owner User and the initial compliance profile
    in one atomic transaction. Cross-checks (GSTIN state vs state_code,
    PAN derived from GSTIN) are done in auth_service.
    """

    # Tenant fields
    business_name: _TrimmedName = Field(
        ...,
        description="The common name your business is known by.",
        examples=["Acme Technologies"],
    )

    legal_name: _TrimmedName = Field(
        ...,
        description="The exact legal name registered on your GST certificate.",
        examples=["Acme Technologies Private Limited"],
    )

    gstin: str = Field(
        ...,
        pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$",
        description="Your 15-character GST Identification Number.",
        examples=["27AAPFU0939F1ZV"],
    )

    address_line: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)] = Field(
        ...,
        description="Complete registered address of the business.",
        examples=["101, Tech Park, Andheri East"],
    )

    city: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)] = Field(
        ...,
        description="City of the business address.",
        examples=["Mumbai"],
    )

    pincode: str = Field(
        ...,
        pattern=r"^[1-9][0-9]{5}$",
        description="6-digit pincode of the business address.",
        examples=["400069"],
    )

    state_code: str = Field(
        ...,
        pattern=r"^[0-9]{2}$",
        description="2-digit GST state code. Must match the first 2 digits of the GSTIN.",
        examples=["27"],
    )

    registration_type: str = Field(
        default="regular",
        pattern=r"^(regular|composition|unregistered)$",
        description="GST registration category: regular, composition or unregistered.",
        examples=["regular"],
    )

    # Owner user fields
    email: EmailStr = Field(
        ...,
        description="Business email of the owner. Used to log in.",
        examples=["acmeltd@gmail.com"],
    )

    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        description="8-72 characters with uppercase, lowercase, digit and one of @$!%*?&.",
        examples=["StrongPass@123"],
    )

    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] = Field(
        ...,
        description="Full name of the owner.",
        examples=["Rahul Sharma"],
    )

    annual_turnover: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description=(
            "Aggregate turnover of the preceding financial year in rupees. "
            "Used for HSN digit requirements. Leave 0 for a new business."
        ),
        examples=["75000000.00"],
    )

    is_msme: bool = Field(
        default=False,
        description="True if registered as an MSME.",
    )

    composition_turnover: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description="Only for composition scheme businesses. 0 for regular taxpayers.",
    )

    @field_validator("business_name")
    @classmethod
    def clean_business_name(cls, v: str) -> str:
        """Blocks angle brackets (XSS) and collapses repeated spaces."""
        if re.search(r"[<>]", v):
            raise ValueError("Business name cannot contain '<' or '>' characters.")
        return re.sub(r"\s+", " ", v)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """Length (8-72) is already checked by Field; this checks complexity."""
        if not _PASSWORD_PATTERN.match(value):
            raise ValueError(
                "Password must contain uppercase, lowercase, digit, "
                "and a special character (@$!%*?&)."
            )
        return value


# LOGIN

class LoginRequest(BaseModel):
    """Used by: POST /auth/login. Email and password only."""
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


# TOKEN RESPONSES

class TokenResponse(BaseModel):
    """
    Returned by: POST /auth/login.
    access_token  -> sent in the Authorization: Bearer header on every request.
    refresh_token -> stored securely, used only to get new access tokens.
    """
    access_token: str
    refresh_token: str
    token_type: str = Field(default="bearer")


class AccessTokenResponse(BaseModel):
    """Returned by: POST /auth/refresh. A new access token only."""
    access_token: str
    token_type: str = Field(default="bearer")


class RefreshRequest(BaseModel):
    """Used by: POST /auth/refresh."""
    refresh_token: str


# INTERNAL: JWT PAYLOAD

class TokenPayload(BaseModel):
    """
    Not a request or response schema. The decoded JWT claims, produced by
    security.decode_token() and handed to endpoints by get_current_user().
    sub = user_id.
    """
    sub: UUID
    tenant_id: UUID
    role: UserRole
    jti: UUID
    type: str


# USER RESPONSE

class UserResponse(BaseModel):
    """
    Safe outbound representation of a User. hashed_password is
    deliberately NOT included.
    """
    model_config = {"from_attributes": True}

    id: UUID
    tenant_id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class RegistrationResponse(BaseModel):
    """
    Returned by POST /auth/register. No tokens are issued: the user must
    log in to obtain a session.
    """
    model_config = {"from_attributes": True}

    message: str = Field(default="Registration successful. Please log in to continue.")
    next_step: str = Field(default="/auth/login")
    tenant_id: UUID
    email: str