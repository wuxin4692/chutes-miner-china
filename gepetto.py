"""
Gepetto - coordinate all the things.
"""

import aiohttp
import asyncio
import orjson as json
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, Any
from sqlalchemy import select
from api.config import settings
from api.redis_pubsub import RedisListener
from api.auth import sign_request
from api.database import SessionLocal
from api.chute.schemas import Chute
from api.server.schemas import Server
from api.gpu.schemas import GPU
from api.deployment.schemas import Deployment
import api.k8s as k8s


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
        self.setup_handlers()

    def setup_handlers(self):
        """
        Configure the various event listeners/handlers.
        """
        self.pubsub.on_event("gpu_added")(self.gpu_added)
        self.pubsub.on_event("server_removed")(self.server_removed)
        self.pubsub.on_event("node_removed")(self.node_removed)
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

    async def undeploy(self, deployment_id: str):
        """
        Delete a deployment.
        """
        logger.info(f"Removing all traces of deployment: {deployment_id}")

        # Clean up the database.
        instance_id = None
        validator_hotkey = None
        async with SessionLocal() as session:
            deployment = (
                await session.execute(
                    select(Deployment).where(Deployment.deployment_id == deployment_id)
                )
            ).scalar_one_or_none()
            if deployment:
                instance_id = deployment.instance_id
                validator_hotkey = deployment.validator
                await session.delete(deployment)
                await session.commit()

        # Clean up the validator's instance record.
        if instance_id:
            valis = [
                validator
                for validator in settings.validators
                if validator.hotkey == validator_hotkey
            ]
            if valis:
                vali = valis[0]
                try:
                    async with aiohttp.ClientSession() as session:
                        headers, _ = sign_request(purpose="instances")
                        async with session.delete(
                            f"{vali.api}/instances/{instance_id}", headers=headers
                        ) as resp:
                            if resp.status not in (200, 404):
                                raise Exception(
                                    f"status_code={resp.status}, response text: {await resp.text()}"
                                )
                            elif resp.status == 200:
                                logger.info(f"Deleted instance from validator {validator_hotkey}")
                            else:
                                logger.info(
                                    f"{instance_id=} already purged from {validator_hotkey=}"
                                )
                except Exception:
                    logger.warning(f"Error purging {instance_id=} from {validator_hotkey=}")

        # Purge in k8s if still there.
        await k8s.undeploy(deployment_id)

        logger.success(f"Removed {deployment_id=}")

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
        all_deployments = set()
        k8s_chutes = k8s.get_deployed_chutes()
        k8s_chute_ids = {c["deployment_id"] for c in k8s_chutes}
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
                    tasks.append(asyncio.create_task(self.undeploy(deployment.deployment_id)))

                remote = (self.remote_chutes.get(deployment.validator) or {}).get(
                    deployment.chute_id
                )
                if not remote or remote["version"] != deployment.version:
                    logger.warning(
                        f"Chute: {deployment.chute_id} version={deployment.version} on validator {deployment.validator} not found"
                    )
                    tasks.append(asyncio.create_task(self.undeploy(deployment.deployment_id)))
                    identifier = (
                        f"{deployment.validator}:{deployment.chute_id}:{deployment.version}"
                    )
                    if identifier not in chutes_to_remove:
                        chutes_to_remove.add(identifier)
                        tasks.append(
                            asyncio.create_task(
                                self.chute_removed(
                                    {
                                        "chute_id": deployment.chute_id,
                                        "version": deployment.version,
                                        "validator": deployment.validator,
                                    }
                                )
                            )
                        )

                # Delete any deployments from the DB that either never made it past the stub stage or that aren't in k8s anymore.
                if not deployment.stub and deployment.deployment_id not in k8s_chute_ids:
                    logger.warning(f"Deployment has disappeared from kubernetes: {deployment}")
                    await session.delete(deployment)
                elif deployment.stub and datetime.utcnow() - deployment.created_at >= timedelta(
                    minutes=30
                ):
                    logger.warning(f"Deployment is still a stub after 30 minutes! {deployment}")
                    await session.delete(deployment)

                # Track the list of deployments so we can reconsile with k8s state.
                all_deployments.add(deployment.deployment_id)

            # Purge k8s deployments that aren't tracked anymore.
            for deployment_id in k8s_chute_ids - all_deployments:
                logger.warning(
                    f"Removing kubernetes deployment that is no longer tracked: {deployment_id}"
                )
                tasks.append(asyncio.create_task(self.undeploy(deployment.deployment_id)))

            # GPUs that no longer exist in validator inventory.
            all_gpus = []
            for nodes in self.remote_nodes.values():
                all_gpus += list(nodes)
            async for row in await session.stream(select(GPU)):
                gpu = row[0]
                if gpu.gpu_id not in all_gpus:
                    logger.warning(
                        f"GPU {gpu.gpu_id} is no longer in validator {gpu.validator} inventory"
                    )
                    tasks.append(
                        asyncio.create_task(
                            self.node_removed({"gpu_id": gpu.gpu_id, "validator": gpu.validator})
                        )
                    )

            # Chutes that were removed/outdated.
            async for row in await session.stream(select(Chute)):
                chute = row[0]
                identifier = f"{chute.validator}:{chute.chute_id}:{chute.version}"
                all_chutes.add(identifier)
                remote = (self.remote_chutes.get(deployment.validator) or {}).get(
                    deployment.chute_id
                )
                if (
                    chute.chute_id not in remote
                    or remote["version"] != chute.version
                    and identifier not in chutes_to_remove
                ):
                    logger.warning(
                        f"Chute: {chute.chute_id} version={chute.version} on validator {chute.validator} not found"
                    )
                    tasks.append(
                        asyncio.create_task(
                            self.chute_removed(
                                {
                                    "chute_id": chute.chute_id,
                                    "version": chute.version,
                                    "validator": chute.validator,
                                }
                            )
                        )
                    )
                    chutes_to_remove.add(identifier)

            # New chutes.
            for validator, chutes in self.remote_chutes.items():
                for chute_id, config in chutes:
                    if f"{validator}:{chute_id}:{config['version']}" not in all_chutes:
                        tasks.append(
                            asyncio.create_task(
                                self.chute_upserted(
                                    {
                                        "chute_id": chute_id,
                                        "version": config["version"],
                                        "validator": validator,
                                    }
                                )
                            )
                        )

            # Nodes.
            nodes = await k8s.get_kubernetes_nodes()
            node_ids = {node["server_id"] for node in nodes}
            all_server_ids = set()
            async for row in await session.stream(select(Server)):
                server = row[0]
                if server.server_id not in node_ids:
                    logger.warning(f"Server {server.server_id} no longer in kubernetes node list!")
                    tasks.append(asyncio.create_task(self.server_removed(server.server_id)))
                all_server_ids.add(server.server_id)

            # XXX We won't do the opposite (remove k8s nodes that aren't tracked) because they could be in provisioning status.
            for node_id in node_ids:
                if node_id not in all_server_ids:
                    logger.warning(f"Server/node {node_id} not tracked in inventory, ignoring...")

            await asyncio.gather(*tasks)
