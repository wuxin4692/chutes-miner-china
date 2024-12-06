"""
Helper for kubernetes interactions.
"""

import math
import uuid
import random
import traceback
from loguru import logger
from typing import List, Dict, Any
from kubernetes.client import (
    V1Deployment,
    V1Service,
    V1ObjectMeta,
    V1DeploymentSpec,
    V1DeploymentStrategy,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ResourceRequirements,
    V1ServiceSpec,
    V1ServicePort,
    V1Probe,
    V1HTTPGetAction,
    V1EnvVar,
    V1Volume,
    V1VolumeMount,
    V1ConfigMapVolumeSource,
    V1ConfigMap,
    V1HostPathVolumeSource,
    V1SecurityContext,
    V1EmptyDirVolumeSource,
)
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from api.exceptions import DeploymentFailure
from api.config import settings
from api.database import get_session
from api.server.schemas import Server
from api.chute.schemas import Chute
from api.deployment.schemas import Deployment
from api.config import k8s_core_client, k8s_app_client


async def get_kubernetes_nodes() -> List[Dict]:
    """
    Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes.
    """
    nodes = []
    try:
        node_list = k8s_core_client().list_node(field_selector=None, label_selector="chutes/worker")
        for node in node_list.items:
            gpu_count = int(node.status.capacity["nvidia.com/gpu"])
            node_info = {
                "name": node.metadata.name,
                "validator": node.metadata.labels.get("chutes/validator"),
                "server_id": node.metadata.uid,
                "status": node.status.phase,
                "ip_address": node.metadata.labels.get("chutes/external-ip"),
                "cpu_per_gpu": math.floor(int(node.status.capacity["cpu"]) / gpu_count) - 1 or 1,
                "memory_gb_per_gpu": int(
                    math.floor(int(node.status.capacity["memory"].replace("Ki", "")) / gpu_count)
                    / 1024
                    / 1024
                )
                - 1
                or 1,
            }
            nodes.append(node_info)
    except Exception as e:
        logger.error(f"Failed to get Kubernetes nodes: {e}")
        raise
    return nodes


def is_deployment_ready(deployment):
    """
    Check if a deployment is "ready"
    """
    return (
        deployment.status.available_replicas is not None
        and deployment.status.available_replicas == deployment.spec.replicas
        and deployment.status.ready_replicas == deployment.spec.replicas
        and deployment.status.updated_replicas == deployment.spec.replicas
    )


def _extract_deployment_info(deployment: Any) -> Dict:
    """
    Extract deployment info from the deployment objects.
    """
    deploy_info = {
        "uuid": deployment.metadata.uid,
        "deployment_id": deployment.metadata.labels.get("chutes/deployment-id"),
        "name": deployment.metadata.name,
        "namespace": deployment.metadata.namespace,
        "labels": deployment.metadata.labels,
        "chute_id": deployment.metadata.labels.get("chutes/chute-id"),
        "version": deployment.metadata.labels.get("chutes/version"),
        "node_selector": deployment.spec.template.spec.node_selector,
    }
    deploy_info["ready"] = is_deployment_ready(deployment)
    pod_label_selector = ",".join(
        [f"{k}={v}" for k, v in deployment.spec.selector.match_labels.items()]
    )
    pods = k8s_core_client().list_namespaced_pod(
        namespace=deployment.metadata.namespace, label_selector=pod_label_selector
    )
    deploy_info["pods"] = []
    for pod in pods.items:
        pod_info = {
            "name": pod.metadata.name,
            "phase": pod.status.phase,
        }
        deploy_info["pods"].append(pod_info)
        deploy_info["node"] = pod.spec.node_name
    return deploy_info


async def get_deployment(deployment_id: str):
    """
    Get a single deployment by ID.
    """
    deployment = k8s_app_client().read_namespaced_deployment(
        namespace=settings.namespace,
        name=f"chute-{deployment_id}",
    )
    return _extract_deployment_info(deployment)


async def get_deployed_chutes() -> List[Dict]:
    """
    Get all chutes deployments from kubernetes.
    """
    deployments = []
    label_selector = "chutes/chute=true"
    deployment_list = k8s_app_client().list_namespaced_deployment(
        namespace=settings.namespace, label_selector=label_selector
    )
    for deployment in deployment_list.items:
        deployments.append(_extract_deployment_info(deployment))
        logger.info(
            f"Found chute deployment: {deployment.metadata.name} in namespace {deployment.metadata.namespace}"
        )
    return deployments


async def delete_code(chute_id: str, version: str):
    """
    Delete the code configmap associated with a chute & version.
    """
    try:
        code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute_id}::{version}"))
        k8s_core_client().delete_namespaced_config_map(
            name=f"chute-code-{code_uuid}", namespace=settings.namespace
        )
    except ApiException as exc:
        if exc.status != 404:
            logger.error(f"Failed to delete code reference: {exc}")
            raise


async def undeploy(deployment_id: str):
    """
    Delete a deployment, and associated service.
    """
    try:
        k8s_core_client().delete_namespaced_service(
            name=f"chute-service-{deployment_id}",
            namespace=settings.namespace,
        )
    except Exception as exc:
        logger.warning(f"Error deleting deployment service from k8s: {exc}")
    try:
        k8s_app_client().delete_namespaced_deployment(
            name=f"chute-{deployment_id}",
            namespace=settings.namespace,
        )
    except Exception as exc:
        logger.warning(f"Error deleting deployment from k8s: {exc}")


async def create_code_config_map(chute: Chute):
    """
    Create a ConfigMap to store the chute code.
    """
    code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute.chute_id}::{chute.version}"))
    config_map = V1ConfigMap(
        metadata=V1ObjectMeta(
            name=f"chute-code-{code_uuid}",
            labels={
                "chutes/chute-id": chute.chute_id,
                "chutes/version": chute.version,
            },
        ),
        data={chute.filename: chute.code},
    )
    try:
        k8s_core_client().create_namespaced_config_map(
            namespace=settings.namespace, body=config_map
        )
    except ApiException as e:
        if e.status != 409:
            raise


#def get_used_ports(node_name):
#    ports = set()
#    pods = k8s_core_client().list_pod_for_all_namespaces(field_selector=f'spec.nodeName={node_name}')
#    for pod in pods.items:
#        if pod.spec.host_network:
#            for container in pod.spec.containers:
#                if container.ports:
#                    for port in container.ports:
#                        if port.container_port:
#                            ports.add(port.container_port)
#                        if port.host_port:
#                            ports.add(port.host_port)
#    return sorted(list(ports))


async def deploy_chute(chute: Chute, server: Server):
    """
    Deploy a chute!
    """

    # Make sure the node has capacity.
    #used_ports = get_used_ports(server.name)
    gpus_allocated = 0
    available_gpus = {gpu.gpu_id for gpu in server.gpus if gpu.verified}
    for deployment in server.deployments:
        gpus_allocated += len(deployment.gpus)
        available_gpus -= {gpu.gpu_id for gpu in deployment.gpus}
    if len(server.gpus) - gpus_allocated - chute.gpu_count < 0:
        raise DeploymentFailure(
            f"Server {server.server_id} name={server.name} cannot allocate {chute.gpu_count} GPUs, already using {gpus_allocated} of {len(server.gpus)}"
        )

    # Immediately track this deployment (before actually creating it) to avoid allocation contention.
    deployment_id = str(uuid.uuid4())
    gpus = list([gpu for gpu in server.gpus if gpu.gpu_id in available_gpus])[: chute.gpu_count]
    async with get_session() as session:
        deployment = Deployment(
            deployment_id=deployment_id,
            server_id=server.server_id,
            validator=server.validator,
            chute_id=chute.chute_id,
            version=chute.version,
            active=False,
            verified=False,
            stub=True,
        )
        session.add(deployment)
        deployment.gpus = gpus
        await session.commit()

    # Create the deployment.
    cpu = str(server.cpu_per_gpu * chute.gpu_count)
    ram = str(server.memory_per_gpu * chute.gpu_count) + "Gi"
    code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute.chute_id}::{chute.version}"))
    deployment_labels = {
        "chutes/deployment-id": deployment_id,
        "chutes/chute": "true",
        "chutes/chute-id": chute.chute_id,
        "chutes/version": chute.version,
        "squid-access": "true",
    }

    #while (chute_port := random.randint(8000, 16000)) in used_ports:
    #    logger.warning(f"Port conflict: {chute_port}")
    deployment = V1Deployment(
        metadata=V1ObjectMeta(
            name=f"chute-{deployment_id}",
            labels=deployment_labels,
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            strategy=V1DeploymentStrategy(type="Recreate"),
            selector={"matchLabels": {"chutes/deployment-id": deployment_id}},
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    labels=deployment_labels,
                    annotations={
                        "prometheus.io/scrape": "true",
                        "prometheus.io/path": "/_metrics",
                        "prometheus.io/port": "8000",
                    },
                ),
                spec=V1PodSpec(
                    node_name=server.name,
                    runtime_class_name="nvidia-container-runtime",
                    volumes=[
                        V1Volume(
                            name="code",
                            config_map=V1ConfigMapVolumeSource(
                                name=f"chute-code-{code_uuid}",
                            ),
                        ),
                        V1Volume(
                            name="hf-cache",
                            host_path=V1HostPathVolumeSource(
                                path="/var/lib/hf-cache", type="DirectoryOrCreate"
                            ),
                        ),
                        V1Volume(
                            name="hf-cache-cleanup",
                            config_map=V1ConfigMapVolumeSource(
                                name="chutes-hf-cache-cleaner",
                            ),
                        ),
                        V1Volume(
                            name="tmp",
                            empty_dir=V1EmptyDirVolumeSource(size_limit="10Gi"),
                        ),
                        V1Volume(
                            name="shm",
                            empty_dir=V1EmptyDirVolumeSource(medium="Memory", size_limit="16Gi"),
                        ),
                    ],
                    init_containers=[
                        V1Container(
                            name="cache-init",
                            image="parachutes/hf-cache-cleaner:latest",
                            command=["/bin/bash", "-c"],
                            args=[
                                "mkdir -p /hf-cache && chmod -R 777 /hf-cache && python /scripts/hf_cache_cleanup.py"
                            ],
                            env=[
                                V1EnvVar(
                                    name="HF_HOME",
                                    value="/hf-cache",
                                ),
                                V1EnvVar(
                                    name="HF_CACHE_MAX_AGE_DAYS",
                                    value=str(settings.hf_cache_max_age_days),
                                ),
                                V1EnvVar(
                                    name="HF_CACHE_MAX_SIZE_GB",
                                    value=str(settings.hf_cache_max_size_gb),
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(name="hf-cache", mount_path="/hf-cache"),
                                V1VolumeMount(
                                    name="hf-cache-cleanup",
                                    mount_path="/scripts",
                                ),
                            ],
                            security_context=V1SecurityContext(
                                run_as_user=0,
                                run_as_group=0,
                            ),
                        ),
                    ],
                    containers=[
                        V1Container(
                            name="chute",
                            image=f"{server.validator.lower()}.localregistry.chutes.ai:{settings.registry_proxy_port}/{chute.image}",
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="CHUTES_EXECUTION_CONTEXT",
                                    value="REMOTE",
                                ),
                                V1EnvVar(
                                    name="VLLM_DISABLE_TELEMETRY",
                                    value="1",
                                ),
                                V1EnvVar(
                                    name="NCCL_DEBUG",
                                    value="INFO",
                                ),
                                V1EnvVar(
                                    name="HTTP_PROXY",
                                    value=settings.squid_url or "",
                                ),
                                V1EnvVar(
                                    name="HTTPS_PROXY",
                                    value=settings.squid_url or "",
                                ),
                                V1EnvVar(
                                    name="NCCL_SOCKET_IFNAME",
                                    value="^docker,lo",
                                ),
                                V1EnvVar(
                                    name="NCCL_P2P_DISABLE",
                                    value="1",
                                ),
                                V1EnvVar(
                                    name="NCCL_IB_DISABLE",
                                    value="1",
                                ),
                                V1EnvVar(
                                    name="NCCL_SHM_DISABLE",
                                    value="0",
                                ),
                                V1EnvVar(
                                    name="NCCL_NET_GDR_LEVEL",
                                    value="0",
                                ),
                                V1EnvVar(
                                    name="CUDA_VISIBLE_DEVICES",
                                    value=",".join([str(idx) for idx in range(chute.gpu_count)]),
                                ),
                                V1EnvVar(name="HF_HOME", value="/hf-cache"),
                            ],
                            resources=V1ResourceRequirements(
                                requests={
                                    "cpu": cpu,
                                    "memory": ram,
                                    "nvidia.com/gpu": str(chute.gpu_count),
                                },
                                limits={
                                    "cpu": cpu,
                                    "memory": ram,
                                    "nvidia.com/gpu": str(chute.gpu_count),
                                },
                            ),
                            volume_mounts=[
                                V1VolumeMount(
                                    name="code",
                                    mount_path=f"/app/{chute.filename}",
                                    sub_path=chute.filename,
                                ),
                                V1VolumeMount(name="hf-cache", mount_path="/hf-cache"),
                                V1VolumeMount(name="tmp", mount_path="/tmp"),
                                V1VolumeMount(name="shm", mount_path="/dev/shm"),
                            ],
                            security_context=V1SecurityContext(
                                # XXX Would love to add this, but vllm (and likely other libraries) love writing files...
                                # read_only_root_filesystem=True,
                                capabilities={"add": ["IPC_LOCK"]},
                            ),
                            command=[
                                "chutes",
                                "run",
                                chute.ref_str,
                                "--port",
                                "8000",
                                "--graval-seed",
                                str(server.seed),
                                "--miner-ss58",
                                settings.miner_ss58,
                                "--validator-ss58",
                                server.validator,
                            ],
                            ports=[{"containerPort": 8000}],
                            readiness_probe=V1Probe(
                                http_get=V1HTTPGetAction(path="/_alive", port=8000),
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
            name=f"chute-service-{deployment_id}",
            labels={
                "chutes/deployment-id": deployment_id,
                "chutes/chute": "true",
                "chutes/chute-id": chute.chute_id,
                "chutes/version": chute.version,
            },
        ),
        spec=V1ServiceSpec(
            type="NodePort",
            external_traffic_policy="Local",
            selector={
                "chutes/deployment-id": deployment_id,
            },
            ports=[V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
        ),
    )

    try:
        created_service = k8s_core_client().create_namespaced_service(
            namespace=settings.namespace, body=service
        )
        created_deployment = k8s_app_client().create_namespaced_deployment(
            namespace=settings.namespace, body=deployment
        )
        deployment_port = created_service.spec.ports[0].node_port
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.deployment_id == deployment_id)
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if not deployment:
                raise DeploymentFailure("Deployment disappeared mid-flight!")
            deployment.host = server.ip_address
            deployment.port = deployment_port
            deployment.stub = False
            await session.commit()
            await session.refresh(deployment)

        return deployment, created_deployment, created_service
    except ApiException as exc:
        try:
            k8s_core_client().delete_namespaced_service(
                name=f"chute-service-{deployment_id}",
                namespace=settings.namespace,
            )
        except Exception:
            ...
        try:
            k8s_core_client().delete_namespaced_deployment(
                name=f"chute-{deployment_id}",
                namespace=settings.namespace,
            )
        except Exception:
            ...
        raise DeploymentFailure(
            f"Failed to deploy chute {chute.chute_id} with version {chute.version}: {exc}\n{traceback.format_exc()}"
        )
