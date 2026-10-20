import re

from sqlalchemy.exc import IntegrityError

_CONSTRAINT_IN_MESSAGE = re.compile(r'constraint "([^"]+)"')


def get_constraint_name(exc: IntegrityError) -> str | None:
    """
    Name of the violated constraint, for routing IntegrityErrors by name.

    Works with asyncpg (name on the underlying error, reached through
    __cause__) and psycopg2 (name on .diag). Falls back to parsing the
    message text, e.g. 'violates unique constraint "uq_tenant_email"'.
    """
    orig = exc.orig
    for candidate in (orig, getattr(orig, "__cause__", None)):
        if candidate is None:
            continue
        name = getattr(candidate, "constraint_name", None)
        if name:
            return name
        name = getattr(getattr(candidate, "diag", None), "constraint_name", None)
        if name:
            return name

    match = _CONSTRAINT_IN_MESSAGE.search(str(orig))
    return match.group(1) if match else None