"""
Individual GPU ORM.
"""

from sqlalchemy import Column, String, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from api.database import Base
from api.associations import deployment_gpus


class GPU(Base):
    __tablename__ = "gpus"

    gpu_id = Column(String, primarykey=True, nullable=False)
    server_id = Column(String, ForeignKey("servers.server_id", ondelete="CASCADE"), nullable=False)
    device_info = Column(JSONB, nullable=False)
    model_short_ref = Column(String, nullable=False)
    validated = Column(Boolean, default=False)

    server = relationship("Server", back_populates="gpus")
    deployments = relationship("Deployment", secondary=deployment_gpus, back_populates="gpus")
