"""
Association tables.
"""

from sqlalchemy import Column, String, ForeignKey, Table, UniqueConstraint
from api.database import Base


# Deployment -> GPUs association table.
deployment_gpus = Table(
    "deployment_gpus",
    Base.metadata,
    Column(
        "deployment_id",
        String,
        ForeignKey("deployments.deployment_id", ondelete="CASCADE"),
    ),
    Column("gpu_id", String, ForeignKey("gpu.gpu_id", ondelete="CASCADE")),
    UniqueConstraint("gpu_id", name="uq_deployment_gpu"),
)
