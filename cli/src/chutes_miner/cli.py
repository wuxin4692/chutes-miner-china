import json
import asyncio
import aiohttp
import typer
from chutes_miner.util import sign_request

app = typer.Typer(no_args_is_help=True)


def add_node(
    name: str = typer.Option(..., help="Name of the server/node"),
    validator: str = typer.Option(..., help="Validator ss58 this node is allocated to"),
    hourly_cost: float = typer.Option(..., help="Hourly cost, used in optimizing autoscaling"),
    gpu_short_ref: str = typer.Option(..., help="GPU short reference"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Entrypoint for adding a new kubernetes node.
    """

    async def _add_node():
        nonlocal name, validator, hourly_cost, gpu_short_ref, hotkey, miner_api
        async with aiohttp.ClientSession(raise_for_status=False) as session:
            payload = {
                "name": name,
                "validator": validator,
                "hourly_cost": hourly_cost,
                "gpu_short_ref": gpu_short_ref,
            }
            headers, payload_string = sign_request(hotkey, payload=payload)
            async with session.post(
                f"{miner_api.rstrip('/')}/servers/",
                headers=headers,
                data=payload_string,
                timeout=900,
            ) as resp:
                if resp.status != 200:
                    print(f"\033[31mError adding node:\n{await resp.text()}\033[0m")
                    resp.raise_for_status()
                async for content in resp.content:
                    if content.strip():
                        payload = json.loads(content.decode()[6:])
                        print(f"\033[34m{payload['timestamp']}\033[0m {payload['message']}")

    asyncio.run(_add_node())


def delete_node(
    name: str = typer.Option(..., help="Name of the server/node"),
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Entrypoint for deleting a kubernetes node.
    """

    async def _delete_node():
        nonlocal name, hotkey, miner_api
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, payload_string = sign_request(hotkey, purpose="management")
            async with session.delete(
                f"{miner_api.rstrip('/')}/servers/{name}",
                headers=headers,
            ) as resp:
                print(json.dumps(await resp.json(), indent=2))

    asyncio.run(_delete_node())


def purge_deployments(
    hotkey: str = typer.Option(..., help="Path to the hotkey file for your miner"),
    miner_api: str = typer.Option("http://127.0.0.1:32000", help="Miner API base URL"),
):
    """
    Rebalance all chutes - this just deletes all current instances and let's gepetto re-scale for max $$$
    """

    async def _purge_deployments():
        nonlocal hotkey, miner_api
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, payload_string = sign_request(hotkey, purpose="management")
            async with session.delete(
                f"{miner_api.rstrip('/')}/deployments/purge",
                headers=headers,
            ) as resp:
                print(json.dumps(await resp.json(), indent=2))

    asyncio.run(_purge_deployments())


app.command(name="add-node", help="Add a new kubernetes node to your cluster")(add_node)
app.command(name="delete-node", help="Delete a kubernetes node from your cluster")(delete_node)
app.command(name="purge-deployments", help="Purge all deployments, allowing autoscale from scratch")(purge_deployments)


if __name__ == "__main__":
    app()
