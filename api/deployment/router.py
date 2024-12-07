"""
Routes for deployments.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db_session
from api.auth import authorize
from api.gpu.schemas import VerificationArgs
from api.deployment.schemas import Deployment

router = APIRouter()


@router.patch("/{instance_id}")
async def update_deployment(
    instance_id: str,
    verification_args: VerificationArgs,
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(authorize(allow_validator=True)),
):
    """
    Update a deployment (really the only use case is for validators to mark them as verified).
    """
    deployment = (
        (await db.execute(select(Deployment).where(Deployment.instance_id == instance_id)))
        .unique()
        .scalar_one_or_none()
    )
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment with {instance_id=} not found!",
        )
    deployment.verified = verification_args.verified
    await db.commit()
    await db.refresh(deployment)
    return deployment
