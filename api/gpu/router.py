"""
Routes for GPUs.
"""

import orjson as json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db_session
from api.config import settings
from api.auth import authorize
from api.gpu.schemas import GPU, VerificationArgs

router = APIRouter()


@router.patch("/{gpu_id}")
async def update_gpu(
    gpu_id: str,
    verification_args: VerificationArgs,
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(authorize(allow_validator=True)),
):
    """
    Update a GPU (really the only use case is for validators to mark them as verified).
    """
    gpu = (await db.execute(select(GPU).where(GPU.gpu_id == gpu_id))).unique().scalar_one_or_none()
    if gpu is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"GPU with uuid={gpu_id} not found in inventory",
        )
    gpu.verified = verification_args.verified
    await db.commit()
    await db.refresh(gpu)
    if gpu.verified:
        await settings.redis_client.publish(
            "miner_events",
            json.dumps(
                {
                    "event_type": "gpu_added",
                    "event_data": {
                        "gpu_id": gpu_id,
                    },
                }
            ).decode(),
        )
    return gpu
