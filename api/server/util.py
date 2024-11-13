"""
Server uility functions.
"""

import time
import aiohttp
import asyncio
import traceback
from kubernetes.client import (
    V1Node,
    CoreV1Api,
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
    Watch,
)
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from kubernetes.client.rest import ApiException
from typing import Tuple
from typing import Dict
from api.config import settings
from api.database import get_db_session
from api.server.schemas import Server
from api.gpu.schemas import GPU
from api.exceptions import (
    DuplicateServer,
    NonEmptyServer,
    GPUlessServer,
    DeploymentFailure,
    GraValBootstrapFailure,
)
import ipaddress


async def _fetch_devices(url):
    """
    Query the GraVal bootstrap API for device info.
    """
    nonce = str(int(time.time()))
    headers = {
        "X-Chutes-Hotkey": settings.miner_ss58,
        "X-Chutes-Validator": settings.miner_ss58,
        "X-Chutes-Nonce": nonce,
    }
    headers["X-Chutes-Signature"] = settings.miner_keypair.sign(
        ":".join([settings.miner_ss58, settings.miner_ss58, nonce, "graval"])
    ).hex()
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        async with session.get(url, timeout=5) as response:
            return (await response.json())["devices"]


async def gather_gpu_info(
    server_id: str,
    node_object: V1Node,
    graval_deployment: V1Deployment,
    graval_service: V1Service,
    k8s_client: CoreV1Api,
):
    """
    Wait for the graval bootstrap deployments to be ready, then gather the device info.
    """
    deployment_name = graval_deployment.metadata.name
    namespace = graval_deployment.metadata.namespace or "chutes"
    expected_gpu_count = int(node_object.metadata.labels.get("gpu-count", "0"))
    gpu_short_ref = node_object.metadata.labels.get("gpu-short-ref")
    if not gpu_short_ref:
        raise GraValBootstrapFailure("Node does not have required gpu-short-ref label!")

    # Wait for the bootstrap deployment to be ready.
    watch = Watch()
    start_time = time.time()
    deployment_ready = False
    try:
        async for event in watch.stream(
            k8s_client.list_namespaced_deployment,
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
    node_object: V1Node, k8s_client: CoreV1Api
) -> Tuple[V1Deployment, V1Service]:
    """
    Create a deployment of the GraVal base validation service on a node.
    """
    node_name = node_object.metadata.name
    node_labels = node_object.metadata.labels or {}

    # Double check that we don't already have chute deployments.
    existing_deployments = k8s_client.list_namespaced_deployment(
        namespace=settings.namespace,
        label_selector="chute-deployment=true,app=graval-bootstrap",
        field_selector=f"spec.template.spec.nodeName={node_name}",
    )
    if existing_deployments.items:
        raise NonEmptyServer(
            f"Kubnernetes node {node_name} already has one or more chute and/or graval deployments."
        )

    # Make sure the GPU labels are set.
    gpu_count = node_labels.get("gpu-count", "0")
    if not gpu_count or not gpu_count.isdigit() or not 0 < (gpu_count := int(gpu_count)) <= 8:
        raise GPUlessServer(
            f"Kubernetes node {node_name} gpu-count label missing or invalid: {node_labels.get('gpu_count')}"
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
        created_service = k8s_client.create_namespaced_service(
            namespace=settings.namespace, body=service
        )
        created_deployment = k8s_client.create_namespaced_deployment(
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
            k8s_client.delete_namespaced_service(
                name=f"graval-service-{node_name}", namespace="default"
            )
        except Exception:
            ...
        try:
            k8s_client.delete_namespaced_deployment(name=f"graval-{node_name}", namespace="default")
        except Exception:
            ...
        raise DeploymentFailure(f"Failed to deploy GraVal: {str(exc)}:\n{traceback.format_exc()}")


async def track_server(
    node_object: V1Node, k8s_client: CoreV1Api, add_labels: Dict[str, str] = None
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
        node_object = k8s_client.patch_node(name=node_object.metadata.name, body=body)
    labels = current_labels

    # Extract node information from kubernetes meta.
    name = node_object.metadata.name
    kubernetes_id = node_object.metadata.uid

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
            server_id=kubernetes_id,
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
                raise DuplicateServer(f"Server {kubernetes_id} already in database.")
            else:
                raise
        await session.refresh(server)

    return node_object, server
