
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import require_role
from app.schemas.auth import TokenPayload
from app.schemas.tenant_compliance import (
    TenantComplianceResponse, TenantComplianceRequest, 
)
from app.services import tenant_compliance_service


router= APIRouter(
    prefix="/compliance",
    tags=["Compliance"]
)

@router.post(
    "/create_compliance_profile",
    response_model=TenantComplianceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a compliance profile for a new financial year"
)
async def create_compliance_profile(
    request: TenantComplianceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(require_role("owner"))
):
    """
    Called once per financial_year - typically in April after FY close. 
    owner only: this is a statutory declaration, not a routine operation.

    """
    return await tenant_compliance_service.create_or_renew_compliance(
        db,
        tenant_id=current_user.tenant_id,
        request=request
    )