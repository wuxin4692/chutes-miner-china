"""
Gepetto - coordinate all the things.
"""

import aiohttp
import orjson as json
from loguru import logger
from typing import Dict, Any
from api.config import settings
from api.pubsub import RedisListener
from api.auth import sign_request


class Gepetto:
    def __init__(self):
        """
        Constructor.
        """
        self.pubsub = RedisListener()
        self.setup_handlers()
        self.remote_chutes = {validator.hotkey: [] for validator in settings.validators}
        self.remote_images = {validator.hotkey: [] for validator in settings.validators}
        self.remote_instances = {validator.hotkey: [] for validator in settings.validators}
        self.remote_nodes = {validator.hotkey: [] for validator in settings.validators}

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
                ("nodes", "node_id"),
                ("instances", "instance_id"),
            ):
                logger.debug(f"Refreshing {clazz} from {validator.hotkey}...")
                await self._remote_refresh_objects(
                    getattr(self, f"remote_{clazz}"),
                    validator.hotkey,
                    f"{validator.api}/miner/{clazz}/",
                    id_field,
                )
