from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_errors import get_constraint_name
from app.core.pagination import Page, encode_cursor, decode_cursor
from app.core.exceptions import (
    DuplicatePartyGSTINError, InvalidPartyTaxIdentityError, PartyNotFoundError,
)
from app.domain import business_rules
from app.models.party import Party
from app.repositories import party_repository
from app.schemas.party import PartyCreateRequest, PartyUpdateRequest, PartyResponse

_UNIQUE_GSTIN_CONSTRAINT = "uq_party_tenant_gstin"


def _resolve_tax_identity(
    *, gstin: str | None, pan: str | None, state_code: str,
) -> tuple[str | None, str | None]:
    """
    Pure function. Returns the (gstin, pan) to store.

    Without a GSTIN (B2C / unregistered): the client PAN, if any, is kept.
    With a GSTIN: the format must be valid, its first two digits must equal
    state_code, and PAN is derived from characters 3-12 of the GSTIN. A
    client PAN that disagrees is rejected rather than silently overridden.
    """
    if gstin is None:
        return None, pan

    if not business_rules.validate_gstin(gstin):
        raise InvalidPartyTaxIdentityError(f"GSTIN '{gstin}' has an invalid format.")

    if gstin[:2] != state_code:
        raise InvalidPartyTaxIdentityError(
            f"GSTIN '{gstin}' belongs to state code '{gstin[:2]}', "
            f"but state_code '{state_code}' was supplied."
        )

    derived_pan = gstin[2:12]
    if pan is not None and pan != derived_pan:
        raise InvalidPartyTaxIdentityError(
            f"PAN '{pan}' does not match the PAN embedded in GSTIN '{gstin}'."
        )
    return gstin, derived_pan


def _raise_if_duplicate_gstin(exc: IntegrityError, gstin: str | None) -> None:
    """Map the GSTIN unique-index violation to a clean 409. Other errors pass through."""
    constraint = get_constraint_name(exc)
    if constraint == _UNIQUE_GSTIN_CONSTRAINT:
        raise DuplicatePartyGSTINError(gstin or "") from exc


def _editable_values(
    request: PartyCreateRequest | PartyUpdateRequest, *, gstin: str | None, pan: str | None,
) -> dict[str, object]:
    """The editable columns shared by create and update, with resolved tax identity."""
    return {
        "name": request.name,
        "gstin": gstin,
        "pan": pan,
        "address_line1": request.address_line1,
        "address_line2": request.address_line2,
        "city": request.city,
        "pincode": request.pincode,
        "state_code": request.state_code,
        "email": request.email,
        "phone": request.phone,
    }


async def create_party(
    db: AsyncSession, *, tenant_id: UUID, user_id: UUID, request: PartyCreateRequest,
) -> Party:
    """Create a customer or vendor for this tenant. Duplicate GSTIN -> 409."""
    gstin, pan = _resolve_tax_identity(
        gstin=request.gstin, pan=request.pan, state_code=request.state_code,
    )
    values = _editable_values(request, gstin=gstin, pan=pan)

    try:
        async with db.begin():
            party = await party_repository.create(
                db, tenant_id=tenant_id, created_by=user_id,
                party_type=request.party_type, **values,
            )
    except IntegrityError as exc:
        _raise_if_duplicate_gstin(exc, gstin)
        raise
    return party


async def get_party(db: AsyncSession, *, party_id: UUID, tenant_id: UUID) -> Party:
    """Fetch one party. Missing or other-tenant -> 404."""
    async with db.begin():
        party = await party_repository.get_by_id(db, party_id=party_id, tenant_id=tenant_id)
    if party is None:
        raise PartyNotFoundError(str(party_id))
    return party


async def update_party(
    db: AsyncSession, *, party_id: UUID, tenant_id: UUID, user_id: UUID, request: PartyUpdateRequest,
) -> Party:
    """
    Full replace of editable fields. Already-issued invoices are unaffected:
    they hold a frozen snapshot of the party's GSTIN and state.
    """
    gstin, pan = _resolve_tax_identity(
        gstin=request.gstin, pan=request.pan, state_code=request.state_code,
    )
    values = _editable_values(request, gstin=gstin, pan=pan)

    try:
        async with db.begin():
            rows = await party_repository.update_fields(
                db, party_id=party_id, tenant_id=tenant_id, updated_by=user_id, values=values,
            )
            if rows == 0:
                raise PartyNotFoundError(str(party_id))
            party = await party_repository.get_by_id(db, party_id=party_id, tenant_id=tenant_id)
    except IntegrityError as exc:
        _raise_if_duplicate_gstin(exc, gstin)
        raise
    return party


async def set_party_active(
    db: AsyncSession, *, party_id: UUID, tenant_id: UUID, user_id: UUID, is_active: bool,
) -> Party:
    """
    Deactivate or reactivate. A deactivated party cannot be used on NEW
    invoices (invoice_service checks is_active); payments against its
    existing invoices still work. Repeating the call is a no-op success.
    """
    async with db.begin():
        rows = await party_repository.set_active(
            db, party_id=party_id, tenant_id=tenant_id, is_active=is_active, updated_by=user_id,
        )
        if rows == 0:
            raise PartyNotFoundError(str(party_id))
        party = await party_repository.get_by_id(db, party_id=party_id, tenant_id=tenant_id)
    return party


async def list_parties(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    party_type: str | None,
    is_active: bool | None,
    name_prefix: str | None,
    cursor: str | None,
    limit: int,
) -> Page[PartyResponse]:
    """Cursor-paginated party list, alphabetical by name."""
    after = decode_cursor(cursor)
    async with db.begin():
        rows = await party_repository.list_page(
            db, tenant_id=tenant_id, party_type=party_type, is_active=is_active,
            name_prefix=name_prefix.strip() if name_prefix else None,
            after=after, limit=limit + 1,
        )

    page_rows = rows[:limit]
    items = [PartyResponse.model_validate(party) for party in page_rows]
    next_cursor = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor(last.name, last.id)
    return Page[PartyResponse](items=items, next_cursor=next_cursor)