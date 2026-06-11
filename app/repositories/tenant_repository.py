from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant     # your existing Tenant ORM model
from app.models.enum import RegistrationType


async def get_by_gstin(db: AsyncSession, *, gstin: str) -> Tenant | None:
    """
    Fetch a tenant by their GSTIN.
    
    Used during registration to check: "is this GSTIN already registered?"
    Returns the Tenant object if found, None if not.
    
    Why check at repository level and not rely on the DB unique constraint?
    The DB constraint is the final guard. But catching it at app level lets
    us return a meaningful error message instead of a raw IntegrityError.
    """
    # select(Tenant) → builds a SELECT * FROM tenants query
    # .where(...)    → adds WHERE gstin = :gstin
    result = await db.execute(
        select(Tenant).where(Tenant.gstin == gstin.upper())
    )
    # .scalar_one_or_none() → returns one Tenant object, or None if not found
    # Raises MultipleResultsFound if somehow two rows match (impossible with UNIQUE)
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, *, tenant_id: UUID) -> Tenant | None:
    """
    Fetch a tenant by primary key.

    Used by admin and tenant management features.
    Returns None if no tenant exists with the given ID.
    """
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    return result.scalar_one_or_none()


async def create(
        db: AsyncSession, 
        *, 
        business_name: str, 
        legal_name:str,
        gstin: str, 
        state_code: str,
        pan:str,
        address_line1:str,
        city:str,
        pincode:str,
        email:str,
        registration_type:RegistrationType,

    ) -> Tenant:
    """
    Insert a new Tenant row.
    
    Does NOT commit — the service layer controls the transaction.
    This is intentional: registration creates both a Tenant AND a User
    in one transaction. If the User insert fails, the Tenant insert
    must also be rolled back. The service manages this.
    """
    tenant = Tenant(
        name=business_name,
        legal_name=legal_name,
        gstin=gstin.upper(),    # normalize: always store GSTIN uppercase
        pan=pan,
        address_line1=address_line1,
        city=city,
        pincode=pincode,
        state_code=state_code,
        email=email.lower(),
        registration_type=registration_type,
    )
    db.add(tenant)           # stages the INSERT — not executed yet
    await db.flush()         # sends INSERT to DB but does NOT commit
                             # flush() gives us the tenant.id (auto-generated UUID)
                             # without committing the transaction
                             # We need tenant.id to create the User (foreign key)
    return tenant