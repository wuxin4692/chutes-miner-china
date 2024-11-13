"""
Application-wide settings.
"""

import os
import redis.asyncio as redis
from substrateinterface import Keypair
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    sqlalchemy: str = os.getenv(
        "POSTGRESQL", "postgresql+asyncpg://user:password@127.0.0.1:5432/chutes"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_client: redis.Redis = redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    netuid: int = int(os.getenv("NETUID", "19"))
    subtensor: str = os.getenv("SUBTENSOR_ADDRESS", "wss://entrypoint-finney.opentensor.ai:443")
    graval_bootstrap_image: str = os.getenv(
        "GRAVAL_BOOTSTRAP_IMAGE", "parachutes/graval-bootstrap:latest"
    )
    graval_bootstrap_timeout: int = int(os.getenv("GRAVAL_BOOTSTRAP_TIMEOUT", "300"))
    miner_ss58: str = os.environ["MINER_SS58"]
    miner_keypair: Keypair = Keypair.create_from_seed(os.environ["MINER_SEED"])
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
