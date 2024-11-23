"""
Routes for server management.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import StreamingResponse
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession
from api.database import get_db_session
from api.config import k8s_core_client
from api.auth import authorize
from api.server.schemas import Server, ServerArgs
from api.server.util import bootstrap_server

router = APIRouter()


@router.get("/")
async def list_servers(
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(authorize(allow_miner=True, purpose="management")),
):
    """
    List servers, this can be quite a large response...
    """
    return (await db.execute(select(Server))).scalars().all()


@router.post("/")
async def create_server(
    server_args: ServerArgs,
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(authorize(allow_miner=True, purpose="management")),
):
    """
    Add a new server/kubernetes node to our inventory.  This is a very
    slow/long-running response via SSE, since it needs to do a lot of things.
    """
    node = k8s_core_client().read_node(name=server_args.name)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No kubernetes node with name={server_args.name} found!",
        )
    if (await db.execute(select(exists().where(Server.name == server_args.name)))).scalar():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server with name={server_args.name} is already provisioned!",
        )

    # Stream creation/provisioning details back as they occur.
    async def _stream_provisioning_status():
        async for chunk in bootstrap_server(node, server_args):
            yield chunk

    return StreamingResponse(_stream_provisioning_status())
