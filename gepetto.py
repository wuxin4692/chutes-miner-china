"""
Gepetto - coordinate all the things.
"""

import aiohttp
import asyncio
import orjson as json
from loguru import logger
from typing import Dict, Any
from sqlalchemy import select
from api.config import settings
from api.redis_pubsub import RedisListener
from api.auth import sign_request
from api.database import SessionLocal
from api.chute.schemas import Chute
from api.gpu.schemas import GPU
from api.deployment.schemas import Deployment


class Gepetto:
    def __init__(self):
        """
        Constructor.
        """
        self.pubsub = RedisListener()
        self.remote_chutes = {validator.hotkey: [] for validator in settings.validators}
        self.remote_images = {validator.hotkey: [] for validator in settings.validators}
        self.remote_instances = {validator.hotkey: [] for validator in settings.validators}
        self.remote_nodes = {validator.hotkey: [] for validator in settings.validators}
        self.remote_metrics = {validator.hotkey: [] for validator in settings.validators}
        # self.setup_handlers()

    def setup_handlers(self):
        """
        Configure the various event listeners/handlers.
        """
        self.pubsub.on_event("gpu_added")(self.gpu_added)
        self.pubsub.on_event("server_removed")(self.node_removed)
        self.pubsub.on_event("chute_removed")(self.chute_removed)
        self.pubsub.on_event("chute_upserted")(self.chute_upserted)
        self.pubsub.on_event("bounty")(self.bounty)

    @staticmethod
    async def _remote_refresh_objects(
        pointer: Dict[str, Any],
        hotkey: str,
        url: str,
        id_key: str,
    ):
        """
        Refresh images/chutes from validator(s).
        """
        async with aiohttp.ClientSession() as session:
            headers, _ = sign_request(purpose="miner")
            updated_items = {}
            async with session.get(url, headers=headers) as resp:
                async for content_enc in resp.content:
                    content = content_enc.decode()
                    if content.startswith("data: "):
                        data = json.loads(content[6:])
                        updated_items[data[id_key]] = data
            pointer[hotkey] = updated_items

    async def remote_refresh_all(self):
        """
        Refresh chutes from the validators.
        """
        for validator in settings.validators:
            for clazz, id_field in (
                ("chutes", "chute_id"),
                ("images", "image_id"),
                ("nodes", "uuid"),
                ("instances", "instance_id"),
                ("metrics", "chute_id"),
            ):
                logger.debug(f"Refreshing {clazz} from {validator.hotkey}...")
                await self._remote_refresh_objects(
                    getattr(self, f"remote_{clazz}"),
                    validator.hotkey,
                    f"{validator.api}/miner/{clazz}/",
                    id_field,
                )

    async def reconsile(self):
        """
        Put our local system back in harmony with the validators.
        """
        try:
            await self.remote_refresh_all()
        except Exception as exc:
            logger.error(f"Failed to refresh remote resources: {exc}")
            return

        # Compare local items to validators' inventory.
        tasks = []
        chutes_to_remove = set()
        all_chutes = set()
        async with SessionLocal() as session:
            # Clean up based on deployments/instances.
            async for row in await session.stream(select(Deployment)):
                deployment = row[0]
                if deployment.instance_id not in (
                    self.remote_instances.get(deployment.validator) or {}
                ):
                    logger.warning(
                        f"Deployment: {deployment.deployment_id} (instance_id={deployment.instance_id}) on validator {deployment.validator} not found"
                    )
                    tasks.append(self.undeploy(deployment.deployment_id))

                if deployment.chute_id not in (self.remote_chutes.get(deployment.validator) or {}):
                    logger.warning(
                        f"Chute: {deployment.chute_id} version={deployment.version} on validator {deployment.validator} not found"
                    )
                    tasks.append(self.undeploy(deployment.deployment_id))
                    if deployment.chute_id not in chutes_to_remove:
                        chutes_to_remove.add(deployment.chute_id)
                        tasks.append(
                            self.chute_removed(
                                {"chute_id": deployment.chute_id, "validator": deployment.validator}
                            )
                        )

            # GPUs that no longer exist in validator inventory.
            all_gpus = []
            for nodes in self.remote_nodes.values():
                all_gpus += list(nodes)
            async for row in await session.stream(select(GPU)):
                gpu = row[0]
                if gpu.gpu_id not in all_gpus:
                    tasks.append(
                        self.node_removed({"gpu_id": gpu.gpu_id, "validator": gpu.validator})
                    )

            # Chutes that were removed/outdated.
            async for row in await session.stream(select(Chute)):
                chute = row[0]
                all_chutes.add(f"{chute.validator}:{chute.chute_id}")
                if (
                    chute.chute_id not in (self.remote_chutes.get(chute.validator) or {})
                    and chute.chute_id not in chutes_to_remove
                ):
                    logger.warning(
                        f"Chute: {chute.chute_id} version={chute.version} on validator {chute.validator} not found"
                    )
                    tasks.append(
                        self.chute_removed(
                            {"chute_id": chute.chute_id, "validator": chute.validator}
                        )
                    )
                    chutes_to_remove.add(chute.chute_id)

            # New chutes.
            for validator, chutes in self.remote_chutes.items():
                for chute_id in chutes:
                    if f"{validator}:{chute_id}" not in all_chutes:
                        tasks.append(
                            self.chute_upserted({"chute_id": chute_id, "validator": validator})
                        )

            await asyncio.gather(*tasks)
