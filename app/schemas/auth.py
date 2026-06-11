import re
from datetime import datetime
from uuid import UUID
from app.models.enum import UserRole

from pydantic import BaseModel, EmailStr, Field, field_validator
# BaseModel - base class for all Pydantic schemas
# EmailStr - validates that a string is a properly formatted email address
# Field - adds constraints and metadata to fields
# field_validator - a method decorator to run custom validation logic


# PASSWORD VALIDATION
# Defined at module level so it is compiled once and reused across validators
# This regex checks: at least one lowercase, one uppercase, one digit,
# one special character, total 8-72 characters
# Why max 72? bcrypt silently truncates passwords at 72 bytes.
# A password of 100 chars and 73 chars would hash identically.
# Capping at 72 prevents a user from thinking they have a stronger
# password than they actually do.

_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,72}$"
)


# REGISTRATION 

class TenantRegisterRequest(BaseModel):
    """
    Used by: POST /auth/register
    
    This single schema creates BOTH a Tenant record and an owner User record.
    They are created atomically in one database transaction.
    
    Mixing tenant + user fields here is intentional:
    Registration = "I am a new business onboarding onto this platform."
    The business owner and the business are one event.
    """
    # Tenant fields 
    business_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        strip_whitespace=True,    # "  Acme Ltd  " becomes "Acme Ltd"
        description="The common name your business is known by.",
        examples=["Acme Technologies"]
    )

    legal_name: str = Field(
        ..., 
        min_length=2, 
        max_length=255, 
        strip_whitespace=True,
        description="The exact legal name registered on your GST certificate.",
        examples=["Acme Technologies Private Limited"]
    )

    gstin: str = Field(
        ...,
        pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$",
        # This regex validates the GSTIN format:
        # 2 digits (state code) + 5 uppercase letters (PAN prefix) +
        # 4 digits (PAN year/serial) + 1 letter + 1 alphanumeric +
        # literal Z + 1 alphanumeric check digit
        # Example valid: 27AAPFU0939F1ZV
        description="Your 15-character GST Identification Number.",
        examples=["27AAPFU0939F1ZV"]
    )

    address_line: str = Field(
        ..., 
        min_length=5, 
        strip_whitespace=True,
        description="Complete registered address of the business.",
        examples=["101, Tech Park, Andheri East"]
    )

    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Enter city name your business belongs to",
        examples=["Mumbai"],
    )
    
    pincode: str = Field(
        ...,
        max_length=6,
        description="Enter the pincode of the business address",
        examples=["for Bandra it is - 400050 "],
    )

    # 2-digit state code (01-38). Must match first 2 digits of GSTIN.
    # This cross-field validation is handled in auth_service, not here.
    state_code: str = Field(
        ..., 
        pattern=r"^[0-9]{2}$",
        description="Your 2 digit state code number.",
        examples=["27 for Maharashtra"]
    )

    registration_type: str = Field(
        default="regular",
        description="The GST registration category of the business. " \
        "This drives tax calculation and reporting rules. " \
        "Accepted values: 'regular', 'composition', or 'unregistered'.",
        examples=["regular"]
    )

    # Owner user fields 
    # Pydantic validates format automatically. "notanemail" → 422 error.
    email: EmailStr = Field(
        description="Your actual business email ID.",
        examples=["acmeltd@gmail.com"]
    )

    password: str = Field(..., min_length=8, max_length=72)

    full_name: str = Field(
        ..., 
        min_length=1, 
        max_length=255, 
        strip_whitespace=True,
    )

    @field_validator('business_name')
    @classmethod
    def clean_and_validate_business_name(cls, v):
        # 1. Block malicious HTML/Script tags (XSS protection)
        if re.search(r'[<>]', v):
            raise ValueError("Business name cannot contain '<' or '>' characters.")
        
        # 2. Silently fix the "too many spaces" problem
        # This takes "Acme        Ltd" and turns it into "Acme Ltd"
        return re.sub(r'\s+', ' ', v)
    

    @field_validator('email')
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()
    
    @field_validator("gstin")
    @classmethod
    def uppercase_gstin(cls, value: str) -> str:
        return value.upper()

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """
        field_validator runs AFTER Field constraints.
        So by the time we reach here, we know len(value) is already 8-72.
        We only need to check complexity.
        
        @classmethod is required by Pydantic v2 for field_validators.
        cls = the schema class (TenantRegisterRequest), not an instance.
        value = the actual password string being validated.
        """
        if not _PASSWORD_PATTERN.match(value):
            raise ValueError(
                "Password must contain uppercase, lowercase, digit, "
                "and a special character (@$!%*?&)."
            )
        return value    # always return the (possibly transformed) value


# LOGIN 

class LoginRequest(BaseModel):
    """
    Used by: POST /auth/login
    Intentionally minimal — email and password only.
    tenant_id is NOT required here because email lookup is by email alone
    initially, then verified against the user's tenant.
    """
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=72)
    # min_length=1 → empty password should fail validation, not reach DB
    # max_length=72 → bcrypt truncation defense (same reason as above)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


# TOKEN RESPONSES 

class TokenResponse(BaseModel):
    """
    Returned by: POST /auth/login
    Contains both tokens needed to maintain a session.
    
    access_token  → client puts this in Authorization header for every request
    refresh_token → client stores securely, uses ONLY to get new access tokens
    token_type    → always "bearer" — this is the OAuth2 standard term for
                    "put this in Authorization: Bearer <token>"
    """
    access_token: str
    refresh_token: str
    token_type: str = Field(default="bearer")


class AccessTokenResponse(BaseModel):
    """
    Returned by: POST /auth/refresh
    Only issues a new access token — NOT a new refresh token.
    The refresh token continues until it expires or is revoked.
    """
    access_token: str
    token_type: str = Field(default="bearer")


# REFRESH REQUEST 

class RefreshRequest(BaseModel):
    """
    Used by: POST /auth/refresh
    Client sends their stored refresh token to get a new access token.
    """
    refresh_token: str


# INTERNAL — JWT PAYLOAD 

class TokenPayload(BaseModel):
    """
    NOT a request or response schema.
    This is the internal Python object that represents decoded JWT claims.
    
    Used in:
      - core/security.py   → decode_token() returns this
      - core/dependencies.py → get_current_user() yields this to endpoints
    
    NEVER serialized to JSON and sent to clients.
    sub = user_id (UUID), following JWT standard ("subject" claim name)
    """
    sub: UUID           # user_id
    tenant_id: UUID     # mandatory for every DB query
    role: UserRole           # "owner" | "accountant" | "viewer" |"auditor" 
    jti: UUID           # JWT unique ID
    type: str           # "access" | "refresh"


# USER RESPONSE 

class UserResponse(BaseModel):
    """
    Safe outbound representation of a User.
    
    CRITICAL: hashed_password is NOT in this schema.
    Even though the User ORM model has that column, it will never
    appear in any API response because it is not listed here.
    
    model_config from_attributes=True → tells Pydantic it can read
    from ORM model attributes directly (not just from dicts).
    This allows: UserResponse.model_validate(user_orm_object)
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
    Returned by POST /auth/register.

    Confirms the tenant and user were created successfully.
    No tokens are issued here — the user must complete login
    to obtain an authenticated session.

    next_step tells the client exactly where to redirect.
    """
    model_config = {"from_attributes": True}

    message: str = Field(
        default="Registration successful. Please log in to continue."
    )
    next_step: str = Field(default="/auth/login")
    tenant_id: UUID
    email: str