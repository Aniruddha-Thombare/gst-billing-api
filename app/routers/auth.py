from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.auth import (
    TenantRegisterRequest,
    LoginRequest,
    RefreshRequest,
    RegistrationResponse,
    TokenResponse,
    AccessTokenResponse,
)
from app.services import auth_service
from app.core.dependencies import get_current_user
from app.schemas.auth import TokenPayload


# ── ROUTER SETUP ──────────────────────────────────────────────────────────────
router = APIRouter(
    prefix="/auth",         # all endpoints here will be /auth/...
    tags=["Authentication"], # groups endpoints in OpenAPI docs
)


# ── REGISTER ──────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=RegistrationResponse,    # tells FastAPI the shape of the response
    status_code=status.HTTP_201_CREATED,    # 201 = resource was created
    summary="Register new tenant and owner",
)
async def register(
    request: TenantRegisterRequest,   # FastAPI validates the request body
    db: AsyncSession = Depends(get_db),    # DB session injected
):
    """
    Onboards a new business onto the platform.
    Creates a Tenant + owner User in one transaction.
    Returns access + refresh tokens.
    """
    # Router has one job: call the service and return the result
    # No logic here. No if statements. No DB queries.
    return await auth_service.register(db, request=request)


# ── LOGIN ─────────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login and get tokens",
)
async def login(
    request_body: LoginRequest,
    raw_request: Request,             # FastAPI Request object for metadata
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticates existing user credentials.
    Returns access + refresh tokens on success.
    """
    # Extract User-Agent from request headers for device_info
    # This tells the user "logged in from Chrome on Mac" in a sessions list
    device_info = raw_request.headers.get("User-Agent")

    return await auth_service.login(
        db,
        request=request_body,
        device_info=device_info,
    )


# ── REFRESH ───────────────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=AccessTokenResponse,   # only access token returned
    status_code=status.HTTP_200_OK,
    summary="Get new access token using refresh token",
)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Client calls this when their access token expires.
    Validates the refresh token and issues a new access token.
    """
    return await auth_service.refresh(db, request=request)


# ── LOGOUT ────────────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,    # 204 = success, no body returned
    summary="Revoke session",
)
async def logout(
    request: RefreshRequest,     # client sends their refresh token to revoke it
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
    # current_user dependency ensures the user is authenticated
    # before we allow them to log out (prevents logout spam attacks)
):
    """
    Revokes the provided refresh token.
    The 15-minute access token expires naturally.
    """
    await auth_service.logout(db, refresh_token=request.refresh_token, tenant_id=current_user.tenant_id)
    # 204 responses have no body — FastAPI handles this automatically
    # when status_code=204 is set and the function returns None