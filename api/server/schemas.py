"""
Server (kubernetes node) tracking ORM.
"""

from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.database import Base


class Server(Base):
    __tablename__ = "servers"

    server_id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    ip_address = Column(String)
    verification_port = Column(Integer)
    status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    labels = Column(JSONB, nullable=False)

    gpus = relationship("GPU", back_populates="server")
    chutes = relationship("Chute", back_populates="server")
