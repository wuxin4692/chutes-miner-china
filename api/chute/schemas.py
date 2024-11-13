"""
ORM definitions for Chutes.
"""

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import ARRAY
from api.database import Base


class Chute(Base):
    __tablename__ = "chutes"

    chute_id = Column(String, primary_key=True, nullable=False)
    name = Column(String)
    image = Column(String, nullable=False)
    supported_gpus = Column(ARRAY(String), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    deployments = relationship("Deployment", back_populates="chute", cascade="all, delete-orphan")
