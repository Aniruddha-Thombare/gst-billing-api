# A Collection of PURE FUNCTIONS for security operations
import hashlib
from datetime import timedelta, datetime, timezone
from uuid import UUID, uuid4
from typing import Literal

from jose import JWTError, ExpiredSignatureError, jwt
from app.core.exceptions import TokenExpiredError
from passlib.context import CryptContext

from app.config import settings
from app.schemas.auth import TokenPayload
from app.models.enum import UserRole


# _pwd_context - "_" is done intentional this tells python interpreter and other developers 
# that this variable only belongs to this file and do not import this or use it anywhere else.

# bcrypt - a password hashing algorithm which intentionally slows down the Hash password generation.
# It makes the brute force or hacker attacks impractical. 
# This intentional delay makes the process take a fraction of a second
# bcrypt_rounds = 12 - It forces the server's processor to do the hashing math 2^12 (4,096) times.

# deprecated="auto" - this setting will automatically detect old hashes when users log in and allow 
# your system to silently upgrade them to the new standard without locking anyone out.
_pwd_context = CryptContext(
    schemes=["bcrypt"],  
    deprecated="auto",
    bcrypt__rounds=12,
)

# PASSWORD FUNCTIONS 
def hash_password(plain_password:str) -> str:
    """
    Takes a plain text password provided by the user 
    Converts it into Bcrypt hash string
    """
    return _pwd_context.hash(plain_password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Compares a plain text password against a stored bcrypt hash password.
    
    Returns True if they match, False if not.
    Never raises errors — all errors are swallowed and return False.
    
    Called once: on every login attempt.
    """
    return _pwd_context.verify(plain_password, hashed_password)

# REFRESH TOKEN PASSWORDS 

def hash_refresh_token(raw_token: str) -> str:
    """
    Takes a plain-text refresh token, Produces the SHA-256 hex digest of that token

    A refresh token is 256 bits of randomness - impossible to brute force.
    SHA-256 is fast and sufficient.

    JWT payload claims:
      sub — subject (RFC 7519 standard claim) — who the token belongs to
      tenant_id — custom claim — mandatory for every downstream DB query
      role — custom claim — used by require_role() for authorisation
      type — custom claim — "access" or "refresh", prevents cross-use
      jti — JWT ID (RFC 7519) — unique per token, enables future revocation
      iat — issued at (RFC 7519) — when the token was created
      exp — expiry (RFC 7519) — jose validates this automatically on decode
    
    .encode() - encodes it into a SHA-256 hash.
    .hexdigest() - converts that hash string into 64 characters string (nums and letters)

    This hashed string is what we securely store in the refresh_tokens table.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()

# TOKEN CREATION 

def _build_token(
        *,    # force all arguments to be keyword-only
        user_id: UUID, 
        tenant_id: UUID, 
        role: UserRole,
        token_type: Literal["access", "refresh"],
        expires_delta: timedelta,
) -> str:
    """
    PRIVATE function. All token creation goes through here.
    Having ONE place where tokens are built means:
      - one place to audit
      - one place to add new claims
      - no inconsistency between access and refresh tokens

    The * at the start forces callers to write:
      _build_token(user_id=x, tenant_id=y, ...)  
    instead of positional args which are easy to mix up.

    """
    now = datetime.now(tz=timezone.utc)

    expire = now + expires_delta

    payload = {
        # who this token belongs to
        "sub": str(user_id),  

         # JWT standard claim name, Critical - enables tenant isolation 
        "tenant_id": str(tenant_id),
                                    
        # Every query uses this - "owner" | "accountant" | "viewer" | "auditor"
        "role": role, 

        # Used by permission checks - "access" or "refresh"
        # Prevents refresh tokens being used as access tokens or vice versa
        "type": token_type,

        # JWT ID - unique per token, specific access tokens on logout 
        # Future use: store in Redis to revoke 
        "jti": str(uuid4()),

        # issued at - when was this token created 
        "iat": now, 

        # expiry - jose validates this automatically
        "exp": expire, 
    }

    # jwt.encode - signs the payload with our secret key 
    # The result is a string: "header.payload.signature"
    # Anyone can decode the header and payload (they are base64, not encrypted).
    # But only someone with our secret key can produce a valid signature
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,

    )

def create_access_token(user_id: UUID, tenant_id: UUID, role:str) -> str:
    """
    It Issues a 15-minute access token.
    
    This token is sent with EVERY API request in the Authorization header:
      Authorization: Bearer <access_token>
    
    The endpoint reads it, decodes it, and trusts the claims inside
    WITHOUT hitting the database. That is the performance advantage of JWT.

    """
    return _build_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

def create_refresh_token(user_id: UUID, tenant_id: UUID, role: str) -> str:
    """
    It issues a 7 day refresh token. 
    This token is stored: 
        - client stores the raw token (in HttpOnly cookie or secure storage)
        - DB stores the SHA-256 hash of the token 
    
    when the access token expires, client sends the refresh token to POST/auth/refresh.
    If valid and not revoked - new access token issued. 

    MUST NEVER be sent to any endpoint other than /auth/refresh. 
    The "type": "refresh" claim enforces this in decode_token(). 
    """
    return _build_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

# TOKEN DECODING 

class TokenDecodeError(Exception):
    """
    Raised when token decoding fails for ANY reason:
      - signature invalid (token was tampered with)
      - token expired
      - wrong token type (refresh sent where access expected)
      - payload malformed (missing required claims)
    
    Deliberately one exception type — the caller (dependency.py) maps
    ALL of these to HTTP 401. The user does not need to know which specific
    check failed. That information would help attackers.
    """
    pass


def decode_token(
        token: str,
        *,
        expected_type: Literal["access","refresh"],

) -> TokenPayload:
    """
    Decodes a JWT string into a TokenPayload object.
    
    Performs these checks in order:
      1. Signature valid? (jose handles this)
      2. Not expired? (jose handles this via exp claim)
      3. Correct token type? (we check the type claim)
      4. All required claims present? (Pydantic validates this)
    
    If ANY check fails → raises TokenDecodeError
    The caller maps TokenDecodeError → HTTP 401
    
    The expected_type parameter is the CRITICAL security check:
      decode_token(token, expected_type="access")  → only accepts access tokens
      decode_token(token, expected_type="refresh") → only accepts refresh tokens
    
    This prevents a refresh token being used to authenticate API requests.
    """

    try: 
        raw_payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,

            # Note: algorithms is a LIST. Prevents algorithm confusion attacks
            # where an attacker changes the header to use "none" algorithm.
            algorithms=[settings.JWT_ALGORITHM],

        )
    except ExpiredSignatureError as exc:
        # Caught before JWTError — expiry is safe to name explicitly.
        # The exp claim is public (base64, not encrypted).
        # Frontend uses TOKEN_EXPIRED to trigger silent refresh.
        raise TokenExpiredError() from exc
    except JWTError as exc:
        # JWTError covers: expired, invalid signature, malformed
        # We do NOT expose the specific reason to the caller
        raise TokenDecodeError("Token validation failed") from exc
    
    # Type Check - Even though signature is valid take the type claim 
    token_type_in_payload = raw_payload.get("type")
    if token_type_in_payload != expected_type:
        raise TokenDecodeError(
            f"Expected Token type '{expected_type}',"
            f"got '{token_type_in_payload}'"
        )
    
    # SHAPE VALIDATION
    # Pydantic validates that all required fields exist and have correct types
    # If tenant_id is missing or sub is not a valid UUID → ValidationError
    try:
        return TokenPayload(
            sub=UUID(raw_payload["sub"]),
            tenant_id=UUID(raw_payload["tenant_id"]),
            role=raw_payload["role"],
            jti=UUID(raw_payload["jti"]),
            type=raw_payload["type"],
        )
    except (KeyError, ValueError) as exc:
        # KeyError  → a required claim is missing from the payload
        # ValueError → a UUID field contains an invalid value
        raise TokenDecodeError("Token payload is malformed.") from exc

