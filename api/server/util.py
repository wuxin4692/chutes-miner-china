"""
Server uility functions.
"""

import time
import backoff
import aiohttp
import asyncio
import traceback
import api.constants as cst
from loguru import logger
from kubernetes.client import (
    V1Node,
    V1Deployment,
    V1Service,
    V1ObjectMeta,
    V1DeploymentSpec,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ResourceRequirements,
    V1ServiceSpec,
    V1ServicePort,
    V1Probe,
    V1HTTPGetAction,
    V1EnvVar,
    Watch,
)
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from kubernetes.client.rest import ApiException
from typing import Tuple, Dict, List
from api.auth import sign_request
from api.config import settings, Validator
from api.util import sse_message
from api.database import get_db_session
from api.server.schemas import Server, ServerArgs
from api.gpu.schemas import GPU
from api.exceptions import (
    DuplicateServer,
    NonEmptyServer,
    GPUlessServer,
    DeploymentFailure,
    GraValBootstrapFailure,
)
import ipaddress


@backoff.on_exception(
    backoff.constant,
    Exception,
    jitter=None,
    interval=3,
    max_tries=5,
)
async def _fetch_devices(url):
    """
    Query the GraVal bootstrap API for device info.
    """
    nonce = str(int(time.time()))
    headers = {
        cst.HOTKEY_HEADER: settings.miner_ss58,
        cst.VALIDATOR_HEADER: settings.miner_ss58,
        cst.NONCE_HEADER: nonce,
    }
    headers[cst.SIGNATURE_HEADER] = settings.miner_keypair.sign(
        ":".join([settings.miner_ss58, settings.miner_ss58, nonce, "graval"])
    ).hex()
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        async with session.get(url, timeout=5) as response:
            return (await response.json())["devices"]


async def gather_gpu_info(
    server_id: str,
    validator: str,
    node_object: V1Node,
    graval_deployment: V1Deployment,
    graval_service: V1Service,
) -> List[GPU]:
    """
    Wait for the graval bootstrap deployments to be ready, then gather the device info.
    """
    deployment_name = graval_deployment.metadata.name
    namespace = graval_deployment.metadata.namespace or "chutes"
    expected_gpu_count = int(node_object.metadata.labels.get("nvidia.com/gpu.count", "0"))
    gpu_short_ref = node_object.metadata.labels.get("gpu-short-ref")
    if not gpu_short_ref:
        raise GraValBootstrapFailure("Node does not have required gpu-short-ref label!")

    # Wait for the bootstrap deployment to be ready.
    watch = Watch()
    start_time = time.time()
    deployment_ready = False
    try:
        async for event in watch.stream(
            settings.k8s_core_client().list_namespaced_deployment,
            namespace=namespace,
            field_selector=f"metadata.name={deployment_name}",
            timeout_seconds=settings.graval_bootstrap_timeout,
        ):
            deployment = event["object"]
            if deployment.status.conditions:
                for condition in deployment.status.conditions:
                    if condition.type == "Failed" and condition.status == "True":
                        raise GraValBootstrapFailure(f"Deployment failed: {condition.message}")
            if (deployment.status.ready_replicas or 0) == deployment.spec.replicas:
                deployment_ready = True
                break
            if (delta := time.time() - start_time) >= settings.graval_bootstrap_timeout:
                raise TimeoutError(f"GraVal bootstrap deployment not ready after {delta} seconds!")
            await asyncio.sleep(1)
    except Exception as exc:
        raise GraValBootstrapFailure(f"Error waiting for graval bootstrap deployment: {exc}")
    if not deployment_ready:
        raise GraValBootstrapFailure("GraVal bootstrap deployment never reached ready state.")

    # Configure our validation host/port.
    node_port = None
    node_ip = None
    for port in graval_service.spec.ports:
        if port.node_port:
            node_port = port.node_port
            break
    for addr in node_object.status.addresses:
        if addr.type == "ExternalIP":
            node_ip = addr.address
            break
    if not node_port or not node_ip:
        raise GraValBootstrapFailure("GraVal bootstrap service did not result in external IP/port")

    # Query the GPU information.
    devices = None
    try:
        devices = await _fetch_devices("http://{node_ip}:{node_port}/devices")
        assert devices
        assert len(devices) == expected_gpu_count
    except Exception as exc:
        raise GraValBootstrapFailure(
            f"Failed to fetch devices from GraVal bootstrap: {node_ip}:{node_port}/devices: {exc}"
        )

    # Store inventory.
    gpus = []
    async with get_db_session() as session:
        for device_id in range(len(devices)):
            device_info = devices[device_id]
            gpu = GPU(
                server_id=server_id,
                validator=validator,
                gpu_id=device_info["uuid"],
                device_info=device_info,
                model_short_ref=gpu_short_ref,
                validated=False,
            )
            session.add(gpu)
            gpus.append(gpu)
        await session.commit()
        for idx in range(len(gpus)):
            await session.refresh(gpus[idx])
    return gpus


async def deploy_graval(
    node_object: V1Node,
) -> Tuple[V1Deployment, V1Service]:
    """
    Create a deployment of the GraVal base validation service on a node.
    """
    node_name = node_object.metadata.name
    node_labels = node_object.metadata.labels or {}

    # Double check that we don't already have chute deployments.
    existing_deployments = settings.k8s_core_client().list_namespaced_deployment(
        namespace=settings.namespace,
        label_selector="chute-deployment=true,app=graval-bootstrap",
        field_selector=f"spec.template.spec.nodeName={node_name}",
    )
    if existing_deployments.items:
        raise NonEmptyServer(
            f"Kubnernetes node {node_name} already has one or more chute and/or graval deployments."
        )

    # Make sure the GPU labels are set.
    gpu_count = node_labels.get("nvidia.com/gpu.count", "0")
    if not gpu_count or not gpu_count.isdigit() or not 0 < (gpu_count := int(gpu_count)) <= 8:
        raise GPUlessServer(
            f"Kubernetes node {node_name} nvidia.com/gpu.count label missing or invalid: {node_labels.get('nvidia.com/gpu.count')}"
        )

    # Create the deployment.
    deployment = V1Deployment(
        metadata=V1ObjectMeta(
            name=f"graval-{node_name}",
            labels={"app": "graval", "chute-deployment": "false", "node": node_name},
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector={"matchLabels": {"app": "graval", "node": node_name}},
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels={"app": "graval", "node": node_name}),
                spec=V1PodSpec(
                    node_name=node_name,
                    containers=[
                        V1Container(
                            name="graval",
                            image=settings.graval_bootstrap_image,
                            env=[
                                V1EnvVar(
                                    name="VALIDATOR_WHITELIST",
                                    value=",".join(
                                        [validator.hotkey for validator in settings.validators]
                                    ),
                                ),
                                V1EnvVar(
                                    name="MINER_HOTKEY_SS58",
                                    value=settings.miner_ss58,
                                ),
                            ],
                            resources=V1ResourceRequirements(
                                requests={
                                    "cpu": str(gpu_count),
                                    "memory": "8Gi",
                                    "nvidia.com/gpu": str(gpu_count),
                                },
                                limits={
                                    "cpu": str(gpu_count),
                                    "memory": "8Gi",
                                    "nvidia.com/gpu": str(gpu_count),
                                },
                            ),
                            ports=[{"containerPort": 8000}],
                            readiness_probe=V1Probe(
                                http_get=V1HTTPGetAction(path="/ping", port=8000),
                                initial_delay_seconds=45,
                                period_seconds=10,
                                timeout_seconds=1,
                                success_threshold=1,
                                failure_threshold=3,
                            ),
                        )
                    ],
                ),
            ),
        ),
    )

    # And the service that exposes it.
    service = V1Service(
        metadata=V1ObjectMeta(
            name=f"graval-service-{node_name}",
            labels={"app": "graval", "node": node_name},
        ),
        spec=V1ServiceSpec(
            type="NodePort",
            selector={"app": "graval", "node": node_name},
            ports=[V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
        ),
    )

    # Deploy!
    try:
        created_service = settings.k8s_core_client().create_namespaced_service(
            namespace=settings.namespace, body=service
        )
        created_deployment = settings.k8s_core_client().create_namespaced_deployment(
            namespace=settings.namespace, body=deployment
        )

        # Track the verification port.
        expected_port = created_service.spec.ports[0].node_port
        async with get_db_session() as session:
            result = await session.execute(
                update(Server)
                .where(Server.server_id == node_object.metadata.uid)
                .values(verification_port=created_service.spec.ports[0].node_port)
                .returning(Server.verification_port)
            )
            port = result.scalar_one_or_none()
            if port != expected_port:
                raise DeploymentFailure(
                    f"Unable to track verification port for newly added node: {expected_port=} actual_{port=}"
                )
            await session.commit()
        return created_deployment, created_service
    except ApiException as exc:
        try:
            settings.k8s_core_client().delete_namespaced_service(
                name=f"graval-service-{node_name}",
                namespace=settings.namespace,
            )
        except Exception:
            ...
        try:
            settings.k8s_core_client().delete_namespaced_deployment(
                name=f"graval-{node_name}",
                namespace=settings.namespace,
            )
        except Exception:
            ...
        raise DeploymentFailure(f"Failed to deploy GraVal: {str(exc)}:\n{traceback.format_exc()}")


async def track_server(
    validator: str, node_object: V1Node, add_labels: Dict[str, str] = None
) -> Tuple[V1Node, Server]:
    """
    Track a new kubernetes (worker/GPU) node in our inventory.
    """
    if not node_object.metadata or not node_object.metadata.name:
        raise ValueError("Node object must have metadata and name")

    # Make sure the labels (in kubernetes) are up-to-date.
    current_labels = node_object.metadata.labels or {}
    labels_to_add = {}
    for key, value in (add_labels or {}).items():
        if key not in current_labels or current_labels[key] != value:
            labels_to_add[key] = value
    if labels_to_add:
        current_labels.update(labels_to_add)
        body = {"metadata": {"labels": current_labels}}
        node_object = settings.k8s_core_client().patch_node(
            name=node_object.metadata.name, body=body
        )
    labels = current_labels

    # Extract node information from kubernetes meta.
    name = node_object.metadata.name
    server_id = node_object.metadata.uid

    # Get public IP address if available.
    ip_address = None
    if node_object.status and node_object.status.addresses:
        for addr in node_object.status.addresses:
            if addr.type == "ExternalIP":
                try:
                    ip = ipaddress.ip_address(addr.address)
                    if not ip.is_private and not ip.is_loopback and not ip.is_link_local:
                        ip_address = addr.address
                        break
                except ValueError:
                    continue

    # Determine node status.
    status = "Unknown"
    if node_object.status and node_object.status.conditions:
        for condition in node_object.status.conditions:
            if condition.type == "Ready":
                status = "Ready" if condition.status == "True" else "NotReady"
                break
    if status != "Ready":
        raise ValueError(f"Node is not yet ready [{status=}]")

    # Track the server in our inventory.
    async with get_db_session() as session:
        server = Server(
            server_id=node_object.metadata.uid,
            validator=validator,
            name=name,
            ip_address=ip_address,
            status=status,
            labels=labels,
        )
        session.add(server)
        try:
            await session.commit()
        except IntegrityError as exc:
            if "UniqueViolationError" in str(exc):
                raise DuplicateServer(
                    f"Server {server_id=} {name=} {server_id=} already in database."
                )
            else:
                raise
        await session.refresh(server)

    return node_object, server


@backoff.on_exception(
    backoff.constant,
    Exception,
    jitter=None,
    interval=3,
    max_tries=5,
)
async def _advertise_nodes(validator: Validator, gpus: List[GPU]):
    """
    Post GPU information to one validator, with retries.
    """
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        headers, payload_string = sign_request(payload=[gpu.dict() for gpu in gpus])
        async with session.post(
            f"{validator.api}/nodes/", data=payload_string, headers=headers
        ) as response:
            data = await response.json()
            nodes = data.get("nodes")
            task_id = data.get("task_id")
            assert len(nodes) == len(gpus)
            assert task_id
            logger.success(
                f"Successfully advertised {len(gpus)} to {validator.hotkey} via {validator.api}"
            )
            return task_id, nodes


@backoff.on_exception(
    backoff.constant,
    Exception,
    jitter=None,
    interval=3,
    max_tries=5,
)
async def check_verification_task_status(validator: Validator, task_id: str) -> bool:
    """
    Check the GPU verification task status.
    """
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        headers, payload_string = sign_request(payload=None, purpose="graval")
        async with session.get(
            f"{validator.api}/nodes/verification_status",
            params={"task_id": task_id},
            headers=headers,
        ) as response:
            data = await response.json()
            if (status := data.get("status")) == "pending":
                return None
            if status in ["error", "failed"]:
                return False
            return True


async def bootstrap_server(node_object: V1Node, server_args: ServerArgs):
    """
    Bootstrap a server from start to finish, yielding SSEs for miner to track status.
    """
    started_at = time.time()

    async def _cleanup(delete_node=True):
        node_name = node_object.metadata.name
        node_uid = node_object.metadata.uid
        try:
            settings.k8s_core_client().delete_namespaced_service(
                name=f"graval-service-{node_name}", namespace=settings.namespace
            )
        except Exception:
            ...
        try:
            settings.k8s_core_client().delete_namespaced_deployment(
                name=f"graval-{node_name}", namespace=settings.namespace
            )
        except Exception:
            ...
        if delete_node:
            async with get_db_session() as session:
                node = (
                    await session.query(Server).where(Server.server_id == node_uid)
                ).scalar_one_or_none()
                if node:
                    session.delete(node)
                await session.commit()

    yield sse_message(
        f"attempting to add node server_id={node_object.metadata.uid} to inventory...",
    )
    seed = None
    try:
        node, server = await track_server(
            server_args.validator,
            node_object,
            add_labels={
                "gpu-short-ref": server_args.gpu_short_ref,
            },
        )

        # Great, now it's in our database, but we need to startup graval so the validator can check the GPUs.
        yield sse_message(
            f"server with server_id={node_object.metadata.uid} now tracked in database, provisioning graval...",
        )
        graval_dep, graval_svc = await deploy_graval(node)

        # Excellent, now gather the GPU info.
        yield sse_message(
            "graval bootstrap deployment/service created, gathering device info...",
        )
        gpus = await gather_gpu_info(
            server.server_id, server_args.validator, node, graval_dep, graval_svc
        )

        # Beautiful, tell the validators about it.
        model_name = gpus[0]["name"]
        yield sse_message(
            f"discovered {len(gpus)} GPUs [{model_name=}] on node, advertising node to {len(settings.validators)} validator(s)...",
        )
        for validator in settings.validators:
            yield sse_message(
                f"advertising node to {validator.hotkey} via {validator.api}...",
            )
            validator_nodes = None
            task_id = None
            try:
                task_id, validator_nodes = await _advertise_nodes(validator, gpus)
            except Exception as exc:
                yield sse_message(
                    f"failed to advertising node to {validator.hotkey} via {validator.api}: {exc}",
                )
                raise
            assert (
                len(set(node["seed"] for node in validator_nodes)) == 1
            ), f"more than one seed produced from {validator.hotkey}!"
            if not seed:
                seed = validator_nodes[0]["seed"]
            else:
                assert (
                    seed == validator_nodes[0]["seed"]
                ), f"validators produced differing seeds {seed} vs {validator_nodes[0]['seed']}"
            yield sse_message(
                f"successfully advertised node {node_object.metadata.uid} to validator {validator.hotkey}, received seed: {seed}"
            )
            async with get_db_session() as session:
                await session.execute(
                    update(Server)
                    .where(Server.server_id == node_object.metadata.uid)
                    .values({"seed": seed})
                )
                await session.commit()

            # Wait for verification from this validator.
            while (status := await check_verification_task_status(validator, task_id)) is None:
                yield sse_message(
                    f"waiting for validator {validator.hotkey} to finish GPU verification..."
                )
                await asyncio.sleep(1)
            if status:
                yield sse_message(
                    f"validator {validator.hotkey} has successfully performed GPU verification"
                )
            else:
                error_message = f"GPU verification failed for {validator.hotkey}, aborting!"
                yield sse_message(error_message)
                GraValBootstrapFailure(error_message)

    except Exception as exc:
        error_message = (
            f"unhandled exception bootstrapping new node: {exc}\n{traceback.format_exc()}"
        )
        logger.error(error_message)
        yield sse_message(error_message)
        await _cleanup(delete_node=True)
        raise
    finally:
        await _cleanup(delete_node=False)

    # Astonishing, everything worked.
    async with get_db_session() as session:
        await session.execute(
            update(GPU).where(GPU.server_id == node_object.metadata.uid).values({"verified": True})
        )
        await session.commit()
    yield sse_message(f"completed server bootstrapping in {time.time() - started_at} seconds!")
