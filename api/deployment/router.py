"""
Routes for deployments.
"""

import asyncio
from loguru import logger
from gepetto import Gepetto
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db_session
from api.auth import authorize
from api.deployment.schemas import Deployment

router = APIRouter()


@router.delete("/purge")
async def purge(
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(authorize(allow_miner=True, purpose="management")),
):
    """
    Purge all deployments, allowing gepetto to re-scale for max $$$
    """
    deployments = []
    gepetto = Gepetto()
    for deployment in (await db.execute(select(Deployment))).unique().scalars().all():
        deployments.append(
            {
                "chute_id": deployment.chute_id,
                "chute_name": deployment.chute.name,
                "server_id": deployment.server_id,
                "server_name": deployment.server.name,
                "gpu_count": len(deployment.gpus),
            }
        )
        logger.warning(
            f"Initiating deletion of {deployment.deployment_id}: {deployment.chute.name} from server {deployment.server.name}"
        )
        asyncio.create_task(gepetto.undeploy(deployment.deployment_id))
    return {
        "status": "initiated",
        "deployments_purged": deployments,
    }
