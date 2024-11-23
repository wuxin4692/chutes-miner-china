"""
Individual GPU ORM.
"""

from pydantic import BaseModel
from sqlalchemy import Column, String, ForeignKey, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from api.database import Base
from api.associations import deployment_gpus


class VerificationArgs(BaseModel):
    verified: bool


class GPU(Base):
    __tablename__ = "gpus"

    gpu_id = Column(String, primarykey=True, nullable=False)
    validator = Column(String)
    device_id = Column(Integer, nullable=False)
    server_id = Column(String, ForeignKey("servers.server_id", ondelete="CASCADE"), nullable=False)
    device_info = Column(JSONB, nullable=False)
    model_short_ref = Column(String, nullable=False)
    verified = Column(Boolean, default=False)

    server = relationship("Server", back_populates="gpus")
    deployment = relationship(
        "Deployment", secondary=deployment_gpus, back_populates="gpus", lazy="joined"
    )
