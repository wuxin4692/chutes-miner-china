"""
Helper for kubernetes interactions.
"""

import math
import uuid
import traceback
from loguru import logger
from typing import List, Dict
from kubernetes.client import (
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
    V1Volume,
    V1VolumeMount,
    V1ConfigMapVolumeSource,
    V1ConfigMap,
)
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from api.exceptions import DeploymentFailure
from api.config import settings
from api.database import SessionLocal
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


async def get_deployed_chutes() -> List[Dict]:
    """
    Get all chutes deployments from kubernets.
    """
    deployments = []
    label_selector = "chutes/chute=true"
    deployment_list = k8s_app_client().list_deployment_for_all_namespaces(
        label_selector=label_selector
    )
    for deployment in deployment_list.items:
        deploy_info = {
            "deployment_id": deployment.metadata.uid,
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "labels": deployment.metadata.labels,
            "chute_id": deployment.metadata.labels.get("chute/chute.chute-id"),
            "version": deployment.metadata.labels.get("chute/chute.version"),
            "node_selector": deployment.spec.template.spec.node_selector,
        }
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
        deployments.append(deploy_info)
        logger.info(
            f"Found chute deployment: {deployment.metadata.name} in namespace {deployment.metadata.namespace}"
        )
    return deployments


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
        k8s_core_client().delete_namespaced_deployment(
            name=f"chute-{deployment_id}",
            namespace=settings.namespace,
        )
    except Exception as exc:
        logger.warning(f"Error deleting deployment from k8s: {exc}")


async def deploy_chute(chute: Chute, server: Server):
    """
    Deploy a chute!
    """

    # Make sure the node has capacity.
    gpus_allocated = 0
    available_gpus = {gpu.gpu_id for gpu in server.gpus}
    for deployment in server.deployments:
        gpus_allocated += deployment.gpu_count
        available_gpus -= {gpu.gpu_id for gpu in deployment.gpus}
    if len(server.gpus) - gpus_allocated - chute.gpu_count < 0:
        raise DeploymentFailure(
            f"Server {server.server_id} name={server.name} cannot allocate {chute.gpu_count} GPUs, already using {gpus_allocated} of {len(server.gpus)}"
        )

    # Immediately track this deployment (before actually creating it) to avoid allocation contention.
    deployment_id = str(uuid.uuid4())
    gpus = list([gpu for gpu in server.gpus if gpu.gpu_id in available_gpus])[: chute.gpu_count]
    async with SessionLocal() as session:
        deployment = Deployment(
            deployment_id=deployment_id,
            validator=server.validator,
            chute_id=chute.chute_id,
            version=chute.version,
            active=False,
            verified=False,
            stub=True,
        )
        deployment.gpus = gpus
        session.add(deployment)
        await session.commit()

    # Enure the code is persisted as a configmap.
    code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute.chute_id}::{chute.version}"))
    config_map = V1ConfigMap(
        metadata=V1ObjectMeta(
            name=f"chute-code-{code_uuid}",
            labels={
                "chute/chute-id": chute.chute_id,
                "chute/version": chute.version,
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

    # Create the deployment.
    deployment_id = str(uuid.uuid4())
    cpu = str(server.cpu_per_gpu * chute.gpu_count)
    ram = str(server.memory_per_gpu * chute.gpu_count) + "Gi"
    deployment = V1Deployment(
        metadata=V1ObjectMeta(
            name=f"chute-{deployment_id}",
            labels={
                "chute/deployment-id": deployment_id,
                "chute/chute": "true",
                "chute/chute-id": chute.chute_id,
                "chute/version": chute.version,
            },
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector={"matchLabels": {"chute/deployment-id": deployment_id}},
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels={"chute/deployment-id": deployment_id}),
                spec=V1PodSpec(
                    node_name=server.name,
                    volumes=[
                        V1Volume(
                            name="code",
                            config_map=V1ConfigMapVolumeSource(
                                name=f"chute-code-{code_uuid}",
                            ),
                        )
                    ],
                    containers=[
                        V1Container(
                            name="chute",
                            image=chute.image,
                            env=[
                                V1EnvVar(
                                    name="CHUTES_EXECUTION_CONTEXT",
                                    value="REMOTE",
                                ),
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
                                    name="code-volume",
                                    mount_path=f"/app/{chute.filename}",
                                    sub_path=chute.filename,
                                )
                            ],
                            command=[
                                "chutes",
                                "run",
                                chute.ref_str,
                                "--port",
                                "8000",
                                "--graval-seed",
                                str(server.graval_seed),
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
                "chute/deployment-id": deployment_id,
                "chute/chute": "true",
                "chute/chute-id": chute.chute_id,
                "chute/version": chute.version,
            },
        ),
        spec=V1ServiceSpec(
            type="NodePort",
            selector={
                "chute/deployment-id": deployment_id,
            },
            ports=[V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
        ),
    )

    try:
        created_service = k8s_core_client().create_namespaced_service(
            namespace=settings.namespace, body=service
        )
        created_deployment = k8s_core_client().create_namespaced_deployment(
            namespace=settings.namespace, body=deployment
        )
        deployment_port = created_service.spec.ports[0].node_port
        async with SessionLocal() as session:
            deployment = (
                await session.query(
                    select(Deployment).where(Deployment.deployment_id == deployment_id)
                )
            ).scalar_one_or_none()
            if not deployment:
                raise DeploymentFailure("Deployment disappeared mid-flight!")
            deployment.host = server.ip_address
            deployment.port = deployment_port
            deployment.stub = False
            await session.commit()
            await session.refresh(deployment)

        return created_deployment, created_service
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
