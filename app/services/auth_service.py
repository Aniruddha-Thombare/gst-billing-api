from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.schemas.auth import TenantRegisterRequest, LoginRequest, RefreshRequest,TokenResponse, RegistrationResponse, AccessTokenResponse
from app.core import security

from app.core.security import TokenDecodeError
from app.repositories import tenant_repository, user_repository, refresh_token_repository
from app.core.exceptions import (
    AuthenticationError,
    DuplicateGSTINError,
    DuplicateEmailError,
    UserInactiveError,
    RefreshTokenRevokedError,
    TokenInvalidError,
    TokenExpiredError
)


async def register(
    db: AsyncSession,
    *,
    request: TenantRegisterRequest,
) -> RegistrationResponse:
    """
    Registers a new business on the platform.
    
    Operations (all atomic — if any fail, everything rolls back):
      1. Check GSTIN not already registered
      2. Create Tenant row
      3. Check email not already in use (within the new tenant)
      4. Hash the password
      5. Create User row with role="owner"
      6. Commit transaction
      7. Issue access + refresh tokens
      8. Store refresh token hash in DB
      9. Return both tokens
    """
    # Step 1: GSTIN uniqueness check
    # We check before inserting to give a clean error message.
    # The DB unique constraint is still there as the final safeguard.
    existing_tenant = await tenant_repository.get_by_gstin(db, gstin=request.gstin)
    if existing_tenant:
        raise DuplicateGSTINError(request.gstin)

    # Steps 2-5 are wrapped in a transaction.
    # async with db.begin() → starts a transaction.
    # If ANY line inside raises an exception → automatic ROLLBACK.
    # If the block exits without exception → automatic COMMIT.
    try: 
        async with db.begin():
            # Step 2: Create tenant
            tenant = await tenant_repository.create(
                db,
                business_name=request.business_name,
                legal_name=request.legal_name,
                gstin=request.gstin.upper(),    # normalize: always store GSTIN uppercase
                pan=request.gstin[2:12],
                address_line1=request.address_line,
                city=request.city,
                pincode=request.pincode,
                state_code=request.state_code,
                email=request.email,
                registration_type=request.registration_type,
            )
            # After flush() inside create(), tenant.id is now available
            # without having committed to the DB yet.
            # Step 3: Email uniqueness check within this new tenant
            existing_user = await user_repository.get_by_email(db, email=request.email)

            # We check if the email exists AND belongs to the exact same tenant
            if existing_user:
                raise DuplicateEmailError(request.email)
            
            #- Hash the password BEFORE storing
            # Never store plain text passwords. Ever.
            hashed_password = security.hash_password(request.password)

            # Step 5: Create the owner user
            user = await user_repository.create(
                db,
                tenant_id=tenant.id,
                email=request.email.lower(),
                hashed_password=hashed_password,
                full_name=request.full_name.strip(),
                role="owner",     # first user of a tenant is always the owner
            )
    except IntegrityError:
        # Race condition guard: two concurrent registrations with the same
        # GSTIN both pass the pre-check then race to insert. The DB unique
        # constraint on gstin catches the second writer.
        raise DuplicateGSTINError(request.gstin)

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
    Authenticates a user and issues a new session.
    
    Operations:
      1. Find user by email
      2. Verify password
      3. Check user is active
      4. Issue tokens
      5. Store refresh token hash in DB
      6. Update last_login_at timestamp
    """
    # Step 1: Find user by email
    user = await user_repository.get_by_email(db, email=request.email)

    # Step 2: Verify password
    # IMPORTANT: we check user is None AND wrong password with the SAME error.
    # "Invalid email or password" — never tell the attacker which part failed.
    # If user is None, we still call verify_password with a dummy hash.
    # Why? To prevent timing attacks:
    #   Without dummy hash: "no user" returns in 0ms, "wrong password" in 250ms.
    #   An attacker can probe emails by measuring response time.
    #   With dummy hash: both cases take ~250ms.
    dummy_hash = "$2b$12$000000000000000000000000000000000000000000000000000000"
    password_is_correct = security.verify_password(
        request.password,
        user.hashed_password if user else dummy_hash,
    )

    if not user or not password_is_correct:
        raise AuthenticationError()

    # Step 3: Check account is active
    if not user.is_active:
        raise UserInactiveError()

    # Steps 4-5: Tokens
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
        # Step 6: Update last login timestamp
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
    Issues a new access token using a valid refresh token.
    
    Operations:
      1. Decode and validate the refresh token JWT
      2. Look up the token hash in DB
      3. Verify it has not been revoked or expired
      4. Issue a new access token
    """
    # Step 1: Decode JWT — verifies signature and expiry
    try:
        payload = security.decode_token(
            request.refresh_token,
            expected_type="refresh",    # CRITICAL: reject access tokens here
        )
    except (TokenDecodeError, TokenExpiredError):
        raise TokenInvalidError()

    # Step 2: Look up in DB — even a valid JWT must be in the DB
    # This is what enables revocation. Without DB check, a stolen
    # refresh token that was "logged out" would still work.
    stored_token = await refresh_token_repository.get_by_raw_token(
        db, 
        raw_token=request.refresh_token,
        tenant_id=payload.tenant_id
    )

    if not stored_token:
        # Token not in DB — was it already used/deleted? Suspicious.
        raise TokenInvalidError()

    # Step 3: Check validity (not revoked, not expired)
    if not stored_token.is_valid:
        raise RefreshTokenRevokedError()

    # Step 4: Issue new access token
    # We do NOT issue a new refresh token here.
    # Refresh token rotation (new refresh token on each use) can be added
    # later. For now, keep the same refresh token for its 7-day lifespan.
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
) -> None:
    """
    Revokes a refresh token, ending the session.
    
    The access token cannot be revoked (stateless JWT).
    It will expire on its own in 15 minutes.
    After logout, the client must discard the access token and
    stop sending it. It will fail on the next token check anyway
    because the DB check happens on refresh, not on every request.
    
    If you need immediate access token revocation, store the JTI
    in Redis with a 15-minute TTL. Check Redis in dependencies.py.
    That is a future enhancement — not needed for day 1.
    """
    async with db.begin():
        await refresh_token_repository.revoke(db, raw_token=refresh_token, tenant_id=tenant_id)