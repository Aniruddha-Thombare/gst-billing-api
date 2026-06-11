from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# HTTPBearer   → FastAPI utility that extracts the token from
#               "Authorization: Bearer <token>" header automatically
# HTTPAuthorizationCredentials → the object HTTPBearer returns, containing the token

from app.core.security import decode_token, TokenDecodeError
from app.core.exceptions import PermissionDeniedError, TokenExpiredError
from app.schemas.auth import TokenPayload
from app.models.enum import UserRole

# Valid roles defined once here — single source of truth.
# require_role() validates against this set at definition time,
# catching typos immediately rather than silently at runtime.
_VALID_ROLES: frozenset[str] = frozenset(role.value for role in UserRole)


# ── BEARER TOKEN EXTRACTOR ────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)
# auto_error=False → if Authorization header is missing, returns None
# instead of raising an error. We handle the None case ourselves below
# so we can return our own error message format.


# ── MAIN AUTH DEPENDENCY ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenPayload:
    """
    The authentication gate for every protected endpoint.
    
    FastAPI calls this before the endpoint function runs.
    
    Flow:
      1. Extract token from Authorization header
      2. Decode and validate the JWT
      3. Return the TokenPayload (contains user_id, tenant_id, role)
    
    If ANY step fails → raises HTTP 401 and the endpoint never runs.
    
    Usage in an endpoint:
      @router.get("/invoices")
      async def list_invoices(current_user: TokenPayload = Depends(get_current_user)):
          # current_user.tenant_id is now available
          # current_user.role is available for permission checks
    """

    # Step 1: Check that Authorization header was present
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Authorization header missing.", "code": "NO_TOKEN"},
            headers={"WWW-Authenticate": "Bearer"},
            # WWW-Authenticate header tells the client what auth method to use
            # Required by HTTP spec when returning 401
        )

    # Step 2: Decode the token
    try:
        payload = decode_token(
            credentials.credentials,   # the raw token string after "Bearer "
            expected_type="access",    # ONLY access tokens accepted here
        )

    except TokenExpiredError as exc:
        # Hand the frontend an explicit code so it can trigger a silent refresh handshake
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": str(exc), "code": "TOKEN_EXPIRED"},
            headers={"WWW-Authenticate": "Bearer error='token_expired'"},
        )
    except TokenDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": str(exc), "code": "TOKEN_INVALID"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload
    # The payload (TokenPayload) is now available in every endpoint
    # that uses Depends(get_current_user)


# ── ROLE-BASED ACCESS CONTROL ─────────────────────────────────────────────────

def require_role(*allowed_roles: str):
    """
    Returns a dependency that enforces role-based access.
    
    This is a FACTORY FUNCTION — it returns a dependency, not a value.
    
    Usage:
      @router.post("/invoices")
      async def create_invoice(
          current_user: TokenPayload = Depends(require_role("owner", "accountant"))
      ):
    
    This endpoint will reject any user with role "viewer" with HTTP 403.
    """
    invalid = frozenset(allowed_roles) - _VALID_ROLES
    if invalid:
        # Fail at startup, not at runtime during a live request.
        raise ValueError(
            f"require_role() received unknown role(s): {invalid}. "
            f"Valid roles are: {_VALID_ROLES}"
        )

    async def _check_role(
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        # get_current_user is resolved first by FastAPI's dependency graph
        # because _check_role declares it via Depends(). Authentication is
        # therefore guaranteed before this line runs.
        if current_user.role not in allowed_roles:
            raise PermissionDeniedError(
                role=current_user.role,
                action=f"one of {allowed_roles}",
            )
        return current_user

    return _check_role
    # Returns the inner function as a callable dependency