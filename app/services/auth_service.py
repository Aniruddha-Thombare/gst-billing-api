import asyncio

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.schemas.auth import (
    TenantRegisterRequest, LoginRequest, RefreshRequest, TokenResponse,
    RegistrationResponse, AccessTokenResponse)
from app.core import security
from app.models.enum import UserRole
from app.domain.business_rules import get_financial_year
from app.core.db_errors import get_constraint_name
from app.core.security import TokenDecodeError
from app.repositories import (
    tenant_repository, user_repository,
    refresh_token_repository, tenant_compliance_repository
)
from app.core.exceptions import (
    AuthenticationError, DuplicateGSTINError, DuplicatePANError, 
    DuplicateEmailError, StateCodeMismatchError, UserInactiveError,
    RefreshTokenRevokedError, TokenInvalidError, TokenExpiredError
)

# A real bcrypt hash, built once at startup. Used when the email does not
# exist, so unknown-email and wrong-password logins take the same time.
_DUMMY_PASSWORD_HASH: str = security.hash_password("timing-defense-dummy-password")


async def register(
    db: AsyncSession,
    *,
    request: TenantRegisterRequest,
) -> RegistrationResponse:
    """
    Registers a new business: tenant + owner user + initial compliance
    profile, all in ONE transaction (any failure rolls back everything).
    Returns no tokens; the user logs in separately.
    """
        # The GSTIN's first two digits ARE the state of registration. A different
    # state_code would corrupt intrastate/interstate tax on every invoice.
    if request.gstin[:2] != request.state_code:
        raise StateCodeMismatchError(request.gstin, request.state_code)

    # bcrypt is CPU-heavy (~250ms). Run it in a thread so the event loop
    # keeps serving other requests, and do it BEFORE the transaction opens
    # so no DB connection is held while hashing.
    hashed_password = await asyncio.to_thread(security.hash_password, request.password)

    try:
        async with db.begin():
            # GSTIN pre-check gives a clean error; the DB constraint is the final safeguard.
            existing_tenant = await tenant_repository.get_by_gstin(db, gstin=request.gstin)
            if existing_tenant:
                raise DuplicateGSTINError(request.gstin)

            existing_user = await user_repository.get_by_email(db, email=request.email)
            if existing_user:
                raise DuplicateEmailError(request.email)

            tenant = await tenant_repository.create(
                db,
                business_name=request.business_name,
                legal_name=request.legal_name,
                gstin=request.gstin.upper(),
                pan=request.gstin[2:12],
                address_line1=request.address_line,
                city=request.city,
                pincode=request.pincode,
                state_code=request.state_code,
                email=request.email,
                registration_type=request.registration_type,
            )

            user = await user_repository.create(
                db,
                tenant_id=tenant.id,
                email=request.email.lower(),
                hashed_password=hashed_password,
                full_name=request.full_name.strip(),
                role=UserRole.OWNER,
            )

            # Financial year is derived server-side from today's date, never
            # client-supplied. Example: today = 2025-01-15 -> FY "2024-25",
            # effective_from = 2024-04-01.
            today = date.today()
            financial_year = get_financial_year(today)
            fy_start_year = int(financial_year.split("-")[0])
            effective_from = date(fy_start_year, 4, 1)

            await tenant_compliance_repository.create(
                db,
                tenant_id=tenant.id,
                financial_year=financial_year,
                annual_turnover=request.annual_turnover,
                composition_turnover=request.composition_turnover,
                is_msme=request.is_msme,
                effective_from=effective_from,
                effective_to=None
            )

    except IntegrityError as exc:
        # Backstop for two identical registrations racing past the checks above.
        constraint = get_constraint_name(exc)
        if constraint == "uq_tenant_gstin":
            raise DuplicateGSTINError(request.gstin) from exc
        if constraint in ("uq_user_email", "uq_tenant_email"):
            raise DuplicateEmailError(request.email) from exc
        if constraint == "uq_tenant_pan":
            # One Tenant per PAN in this MVP.
            raise DuplicatePANError(request.gstin[2:12]) from exc
        raise

    return RegistrationResponse(
        tenant_id=tenant.id,
        email=user.email
    )


async def login(
    db: AsyncSession,
    *,
    request: LoginRequest,
    device_info: str | None = None,
) -> TokenResponse:
    """
    Authenticates a user and issues a new session:
      1. Find user by email (own short transaction)
      2. Verify password (in a thread, no DB connection held)
      3. Check user is active
      4. Issue tokens
      5. Store refresh-token hash + update last login (one transaction)
    """
    async with db.begin():
        user = await user_repository.get_by_email(db, email=request.email)

    # Same error for "no such user" and "wrong password", and the same
    # amount of work for both (dummy hash), so response time leaks nothing.
    password_hash = user.hashed_password if user else _DUMMY_PASSWORD_HASH
    password_is_correct = await asyncio.to_thread(
        security.verify_password, request.password, password_hash,
    )

    if not user or not password_is_correct:
        raise AuthenticationError()

    if not user.is_active:
        raise UserInactiveError()

    access_token = security.create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    refresh_token = security.create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )

    async with db.begin():
        await refresh_token_repository.create(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
            raw_token=refresh_token,
            device_info=device_info,
        )
        await user_repository.update_last_login(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id
        )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


async def refresh(
    db: AsyncSession,
    *,
    request: RefreshRequest,
) -> AccessTokenResponse:
    """
    Issues a new access token from a valid refresh token. A valid JWT alone
    is not enough: the token's hash must exist in the DB and not be revoked.
    """
    try:
        payload = security.decode_token(
            request.refresh_token,
            expected_type="refresh",    # rejects access tokens here
        )
    except (TokenDecodeError, TokenExpiredError):
        raise TokenInvalidError()

    async with db.begin():
        stored_token = await refresh_token_repository.get_by_raw_token(
            db,
            raw_token=request.refresh_token,
            tenant_id=payload.tenant_id
        )

    if not stored_token:
        raise TokenInvalidError()

    if not stored_token.is_valid:
        raise RefreshTokenRevokedError()

    # No refresh-token rotation yet; the same refresh token lives its 7 days.
    access_token = security.create_access_token(
        user_id=payload.sub,
        tenant_id=payload.tenant_id,
        role=payload.role,
    )

    return AccessTokenResponse(access_token=access_token)


async def logout(
    db: AsyncSession,
    *,
    refresh_token: str,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    """
    Revokes a refresh token, ending the session. The access token cannot be
    revoked (stateless JWT) and simply expires in 15 minutes.
    """
    async with db.begin():
        await refresh_token_repository.revoke(
            db, raw_token=refresh_token, tenant_id=tenant_id, user_id=user_id,
        )