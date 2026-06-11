class GSTBillingException(Exception):
    """
    Base class for all application errors and exceptions
    Every domain error inherits from this 

    message - human-readable description (shown to the user)
    code - machine-readable identifier (used by frontend to handle errors)
    status_code - the HTTP status code this maps to
    """
    def __init__(self, message:str, code:str, status_code: int = 400):
        self.message = message 
        self.code = code
        self.status_code = status_code
        super().__init__(message)   # pass message to base Exception class

# AUTHENTICATION EXCEPTIONS


class AuthenticationError(GSTBillingException):
    """
    Triggered when logins fails - email not found, password wrong, user inactive.
    DELIBERATELY vague message — do not tell the attacker which part failed.
    """
    def __init__(self) -> None:
        super().__init__("Invalid email or password.", "AUTHENTICATION_FAILED", 401)


class TokenExpiredError(GSTBillingException):
    """
    Triggered when a user tries to use an access token that is older than 15 minutes.
    """
    def __init__(self)  -> None:
        super().__init__("Token has expired.", "TOKEN_EXPIRED", 401)


class TokenInvalidError(GSTBillingException):
    """
    Triggered when a token's cryptographic signature is fake, or if someone 
    tries to use a 7-day refresh token in a place that requires a 15-minute access token.
    """
    def __init__(self)  -> None:
        super().__init__("Token is invalid.", "TOKEN_INVALID", 401)


class RefreshTokenRevokedError(GSTBillingException):
    """
    Triggered when a user clicks 'Logout', but later tries to use that 
    same old session to get a new access token.
    """
    def __init__(self)  -> None:
        super().__init__("Session has been revoked.", "TOKEN_REVOKED", 401)

# REGISTRATION EXCEPTIONS(used during POST/auth/register)


class DuplicateGSTINError(GSTBillingException):
    """
    Triggered during registration if a business tries to sign up with 
    a GSTIN that is already using our platform.
    """
    def __init__(self, gstin: str)  -> None:
        super().__init__(
            f"GSTIN '{gstin}' is already registered.",
            "DUPLICATE_GSTIN",
            409,    
        )

# USER EXCEPTIONS 
class DuplicateEmailError(GSTBillingException):
    """
    Triggered during registration or user creation if someone tries to 
    use an email that already exists within that specific business.
    """
    def __init__(self, email: str)  -> None:
        super().__init__(
            f"Email '{email}' is already registered.",
            "DUPLICATE_EMAIL",
            409,
        )


class UserInactiveError(GSTBillingException):
    """
    Triggered during login if the business owner has manually blocked 
    or fired this specific employee.
    """
    def __init__(self)  -> None:
        super().__init__(
            "Account is deactivated. Contact your administrator.",
            "USER_INACTIVE",
            403,    
        )


class PermissionDeniedError(GSTBillingException):
    """
    Authenticated user's role does not permit the requested action.
    Raised by require_role() in core/dependencies.py.
    HTTP 403 — identity is known, permission is denied.
    """

    def __init__(self, role: str, action: str) -> None:
        super().__init__(
            f"Role '{role}' is not permitted to perform '{action}'.",
            "PERMISSION_DENIED",
            403,
        )