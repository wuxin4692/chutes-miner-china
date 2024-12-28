"""
Export audit information from our miner.

Information collected:
  - metrics from prometheus about invocation counts and durations
  - prometheus server uptime (so we can discard incongruencies when data may be missing)
  - deployment audit information, so we can check how many inference requests we *should* have gotten, in theory...

The information is then signed with our hotkey and uploaded to the chutes validator, and the hash of the export payload is commited to chain.
"""

import json
import aiohttp
import asyncio
import hashlib
from loguru import logger
from sqlalchemy import text
from datetime import UTC, datetime, timedelta
from prometheus_api_client import PrometheusConnect
from substrateinterface import SubstrateInterface
from api.config import settings, k8s_core_client
from api.database import get_session
from api.auth import sign_request
import api.database.orms  # noqa


def get_prometheus_metrics(end_time) -> dict:
    """
    Query prometheus to get metrics for each chute that ran at least partially during our target time range.
    """
    prom = PrometheusConnect(url="http://prometheus-server")
    query = 'sum(increase(invocation_duration_sum{status="200"}[1h])) by (chutes_deployment_id, chute_id, function)'
    result = prom.custom_query_range(query, start_time=end_time, end_time=end_time, step="1h")
    return [
        {
            "chute_id": item["metric"]["chute_id"],
            "deployment_id": item["metric"]["chutes_deployment_id"],
            "function": item["metric"]["function"],
            "total_seconds": float(item["values"][0][1]),
        }
        for item in result
        if item.get("values") and float(item["values"][0][1]) > 0
    ]


def get_prometheus_uptime() -> float:
    """
    Get the prometheus-server deployment uptime in seconds.
    """
    pods = k8s_core_client().list_namespaced_pod(
        namespace=settings.namespace,
        label_selector="app.kubernetes.io/name=prometheus,app.kubernetes.io/component=server",
    )
    if not pods.items:
        raise ValueError(f"No Prometheus server pods found in namespace {settings.namespace}")
    pod = pods.items[0]
    container_status = next(
        (status for status in pod.status.container_statuses if status.name == "prometheus-server"),
        None,
    )
    if not container_status or not container_status.state.running:
        raise ValueError("Prometheus server container not running")
    start_time = container_status.state.running.started_at
    uptime = int((datetime.now(start_time.tzinfo) - start_time).total_seconds())
    return uptime


async def get_deployment_audit(start_time, end_time) -> list:
    """
    Get deployment audit information.

    Filtering here is just based on having a deleted_at timestamp of null or within our start/end time.
    - if the deployment is not deleted, then it should be included since it's either running
      or pending validation.
    - if it's deleted, we only need to include it in the audit result for this time bucket, otherwise
      it's part of a different audit entry.
    """
    async with get_session() as session:
        query = text("""
           SELECT * FROM deployment_audit
            WHERE deleted_at IS NULL OR (deleted_at >= :start_time AND deleted_at <= :end_time)
        """)
        result = await session.execute(
            query,
            {
                "start_time": start_time.replace(tzinfo=None),
                "end_time": end_time.replace(tzinfo=None),
            },
        )
        results = [dict(row._mapping) for row in result]
        for item in results:
            for key in item:
                if isinstance(item[key], datetime):
                    item[key] = item[key].isoformat()
        return results


async def generate_current_miner_audit_info() -> dict:
    """
    Generate the current time bucket (which is the most recent completed hour) audit info.
    """
    end_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(hours=1)
    logger.info(
        f"Generating audit information for time range: {start_time.isoformat()} through {end_time.isoformat()}"
    )

    prometheus_metrics = get_prometheus_metrics(end_time)
    try:
        prometheus_uptime = get_prometheus_uptime()
    except ValueError:
        prometheus_uptime = -1
    deployment_audit_entries = await get_deployment_audit(start_time, end_time)

    # Display some summary info here.
    uptime_message = "Prometheus has been running the entire audit time slice."
    if prometheus_uptime == -1:
        uptime_message = f"Prometheus uptime could not be determined! Check the prometheus-server deployment in namespace {settings.namespace}!"
    elif prometheus_uptime < 60 * 60:
        uptime_message = f"Prometheus uptime is only {prometheus_uptime} seconds, and could therefore have generated incomplete data."
    logger.info(f"Prometheus status: {uptime_message}")
    unique_functions = set()
    total_seconds = 0.0
    for item in prometheus_metrics:
        unique_functions.add(f"{item['deployment_id']}:{item['function']}")
        total_seconds += item["total_seconds"]
    logger.info(f"Compute time: {total_seconds} across {len(unique_functions)} unique functions")
    logger.info(f"Deployment audit: {len(deployment_audit_entries)} entries")

    # Report string/signature.
    report_data = json.dumps(
        {
            "miner_hotkey": settings.miner_ss58,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "prometheus_message": uptime_message,
            "prometheus_metrics": prometheus_metrics,
            "deployment_audit": deployment_audit_entries,
        }
    ).encode()
    sha256 = hashlib.sha256(report_data).hexdigest()
    return sha256, report_data


def commit(sha256) -> int:
    """
    Commit this bucket of audit data to chain.
    """
    substrate = SubstrateInterface(url=settings.subtensor)
    call = substrate.compose_call(
        call_module="Commitments",
        call_function="set_commitment",
        call_params={"netuid": settings.netuid, "info": {"fields": [[{"Sha256": f"0x{sha256}"}]]}},
    )
    extrinsic = substrate.create_signed_extrinsic(
        call=call,
        keypair=settings.miner_keypair,
    )
    response = substrate.submit_extrinsic(
        extrinsic=extrinsic,
        wait_for_inclusion=True,
        wait_for_finalization=False,
    )
    response.process_events()
    print(response)
    assert response.is_success
    block_hash = response.block_hash
    block_number = substrate.get_block_number(block_hash)
    logger.success(f"Committed checksum {sha256} in block {block_number}")
    return block_number


async def upload(report_data, block_number):
    """
    Upload the report data to the validator.
    """
    headers, payload = sign_request(payload=report_data)
    headers["Content-type"] = "application/json"
    headers["X-Chutes-Block"] = str(block_number)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.chutes.ai/audit/miner_data", headers=headers, data=payload
        ) as resp:
            print(await resp.text())
            resp.raise_for_status()
            logger.success(f"Uploaded report data: {await resp.json()}")


async def main():
    sha256, report_data = await generate_current_miner_audit_info()

    # Commit report checksum to our hotkey's metadata for this netuid.
    # block = commit(sha256)

    # Upload.
    block = 4581635
    await upload(report_data, block)


asyncio.run(main())
