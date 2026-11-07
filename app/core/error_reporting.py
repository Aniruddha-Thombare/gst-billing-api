"""Optional Sentry. No SENTRY_DSN = no-op. Configured so financial data never leaves."""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def init_error_reporting() -> bool:
    """Returns True when Sentry is active."""
    if not settings.SENTRY_DSN:
        logger.info("error_reporting_disabled")
        return False

    import sentry_sdk  # imported lazily: the app runs fine without the package

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        send_default_pii=False,          # no IPs, cookies, auth headers
        max_request_body_size="never",   # bodies hold passwords and amounts
        include_local_variables=False,   # stack-frame locals can hold secrets
        traces_sample_rate=0.0,          # errors only
    )
    logger.info("error_reporting_enabled")
    return True