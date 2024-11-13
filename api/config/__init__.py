"""
Application-wide settings.
"""

import os
import json
import redis.asyncio as redis
from typing import Any
from pydantic import BaseModel
from substrateinterface import Keypair
from pydantic_settings import BaseSettings
from kubernets import client
from kubernetes.config import load_kube_config, load_incluster_config


class Validator(BaseModel):
    hotkey: str
    registry: str
    api: str


def create_kubernetes_client(cls: Any = client.CoreV1Api):
    """
    Create a k8s client.
    """
    try:
        if os.getenv("KUBERNETES_SERVICE_HOST") is not None:
            load_incluster_config()
        else:
            load_kube_config(config_file=os.getenv("KUBECONFIG"))
        return cls()
    except Exception as exc:
        raise Exception(f"Failed to create Kubernetes client: {str(exc)}")


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
    namespace: str = os.getenv("CHUTES_NAMESPACE", "chutes")
    graval_bootstrap_image: str = os.getenv(
        "GRAVAL_BOOTSTRAP_IMAGE", "parachutes/graval-bootstrap:latest"
    )
    graval_bootstrap_timeout: int = int(os.getenv("GRAVAL_BOOTSTRAP_TIMEOUT", "300"))
    miner_ss58: str = os.environ["MINER_SS58"]
    miner_keypair: Keypair = Keypair.create_from_seed(os.environ["MINER_SEED"])
    core_k8s_client: client.CoreV1Api = create_kubernetes_client()
    apps_k8s_client: client.AppsV1Api = create_kubernetes_client(cls=client.AppsV1Api)
    validators: dict = [
        Validator(**item) for item in json.loads(os.environ["VALIDATORS"]["supported"])
    ]
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


settings = Settings()
