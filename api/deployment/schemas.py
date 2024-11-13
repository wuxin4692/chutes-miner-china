"""
Deployment ORM.
"""

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Integer,
)
from api.database import Base
from api.associations import deployment_gpus


class Deployment(Base):
    __tablename__ = "deployments"

    deployment_id = Column(String, primary_key=True, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    chute_id = Column(String, ForeignKey("chutes.chute_id", ondelete="CASCADE"), nullable=False)
    active = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    gpus = relationship(
        "GPU", secondary=deployment_gpus, back_populates="deployment", lazy="joined"
    )
    chute = relationship("Chute", back_populates="instances", lazy="joined")
