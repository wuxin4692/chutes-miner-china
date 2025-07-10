# [中文版] | [English Version](README.md)

# Chutes 矿工节点

原仓库代码 https://github.com/rayonlabs/chutes-miner

本仓库包含在 chutes.ai 无许可、无服务器、以 AI 为中心的算力平台上进行挖矿的所有相关组件。

我们已尝试通过 ansible、helm/kubernetes 自动化大部分流程，因此尽管看起来内容较多，但上手应该相当简单。

本仓库针对在中国网络环境运行进行了一些部分的修改，和安装步骤的详解，会增加安装一些东西

我的想法是尽量不更改源代码 使用另外的软件使他可以在中国网络环境下运行

为了跟官方文档区别开来我增加的部分将使用<font color='red'> 红色文字</font>

## 📋 目录

- [快速概览](#%EF%B8%8F-快速概览)
- [组件概述](#-组件概述)
  - [配置/管理工具](#%EF%B8%8F-配置管理工具)
    - [Ansible](#-ansible)
    - [Wireguard](#-wireguard)
    - [Kubernetes](#%EF%B8%8F-kubernetes)
  - [矿工组件](#-矿工组件)
    - [Postgres](#-postgres)
    - [Redis](#-redis)
    - [GraVal 引导程序](#-graval-引导程序)
    - [Registry Proxy](#-registry-proxy)
    - [API](#-api)
    - [Gepetto](#%EF%B8%8F-gepetto)
- [开始使用](#-开始使用)
  - [使用 Ansible 配置服务器](#1-使用-ansible-配置服务器)
  - [配置先决条件](#2-配置先决条件)
  - [配置环境](#3-配置环境)
  - [使用优化策略更新 Gepetto](#4-使用优化策略更新-gepetto)
  - [在 Kubernetes 集群内部署矿工节点](#5-在-kubernetes-集群内部署矿工节点)
  - [注册](#6-注册)
- [添加服务器到矿工 inventory](#-添加服务器到矿工-inventory)


## ⛏️ 快速概览

在 Chutes 上挖矿的目标是提供尽可能多的算力，同时优化冷启动时间（运行新应用或被抢占的应用）。所有流程都通过 Kubernetes 自动化，并由 `gepetto.py` 脚本协调，以优化成本效率并最大化你的算力份额。

激励基于总算力时间（包括因首次提供代码应用推理而获得的奖励）。

你应该运行各种类型的 GPU，从低成本型号（如 a10、a5000、t4 等）到高性能型号（如 8x H100 节点）。

切勿注册多个 UID，这只会减少你的总算力时间，导致无意义的自我竞争。只需向一个矿工节点添加算力即可。

激励/权重基于 7 天算力总和计算，因此开始挖矿时请保持耐心！我们需要高质量、稳定的长期矿工节点！


## 🔍 组件概述

### 🛠️ 配置/管理工具

#### 🤖 Ansible

虽然并非绝对必要，但我们**强烈建议**所有矿工使用我们提供的 [ansible](https://github.com/ansible/ansible) 脚本来配置服务器。手动设置有许多细微差别和要求，非常困难。

*后续章节将提供有关使用 ansible 脚本的更多信息。*

#### 🔒 Wireguard

Wireguard 是一种快速、安全的 VPN 服务，由 ansible 配置自动创建，当节点不在同一内部网络时，允许节点之间通信。

通常，你可能希望 CPU 实例在一个提供商（如 AWS、Google 等）上，GPU 实例在另一个提供商（如 Latitude、Massed Compute 等）上，并且由于库存原因，每个类型可能有多个提供商。

通过安装 Wireguard，你的 Kubernetes 集群可以跨任意数量的提供商运行，无需额外配置。

*__这由 ansible 脚本自动安装和配置__*

#### ☸️ Kubernetes

整个 Chutes 矿工节点必须在 [kubernetes](https://kubernetes.io/) 中运行。虽然并非绝对必要，但我们建议使用 microk8s（这一切都由 ansible 脚本自动处理）。如果你选择不使用 microk8s，则必须修改或不使用提供的 ansible 脚本。

*__这由 ansible 脚本自动安装和配置__*


### 🧩 矿工组件

*系统有许多组件和活动部分，因此在进行任何操作之前，请务必熟悉每个组件！*

#### 🐘 Postgres

我们在 Chutes 中大量使用 SQLAlchemy/postgres。所有服务器、GPU、部署等都在 postgresql 中跟踪，postgresql 作为有状态集部署在你的 Kubernetes 集群中，并带有持久卷声明。

*__通过 helm 图表部署时，这会自动安装和配置__*

#### 🔄 Redis

Redis 主要用于矿工节点内的发布订阅（pubsub）功能。事件（验证器添加新 Chute、系统添加 GPU、Chute 移除等）会在 Redis 中触发 pubsub 消息，进而触发代码中的各种事件处理程序。

*__通过 helm 图表部署时，这会自动安装和配置__*

#### ✅ GraVal 引导程序

Chutes 使用自定义的 c/CUDA 库来验证显卡：https://github.com/rayonlabs/graval

简而言之，它使用由设备信息播种的矩阵乘法来验证 GPU 的真实性，包括显存容量测试（95% 的总显存必须可用于矩阵乘法）。发送到 Chutes 网络实例的所有流量都使用只能由所宣传的 GPU 解密的密钥进行加密。

当你向 Kubernetes 集群添加新节点时，服务器上的每个 GPU 都必须通过 GraVal 包验证，因此会部署一个引导服务器来完成此操作（自动进行，无需担心）。

每次 Chute 启动/部署时，还需要运行 GraVal 来计算 Chute 部署所在 GPU 所需的解密密钥。

*__这会自动完成__*

#### 🔀 Registry Proxy

为了保持 Chute Docker 镜像的一定私密性（因为并非所有镜像都是公开的），我们在每个矿工节点上部署了一个 registry proxy，通过 bittensor 密钥签名注入身份验证。

每个 Docker 镜像对 kubelet 显示为 `[validator hotkey ss58].localregistry.chutes.ai:30500/[image username]/[image name]:[image tag]`

该子域名指向 127.0.0.1，因此它始终通过 NodePort 路由和本地优先 k8s 服务流量策略从每个 GPU 服务器上的 registry service proxy 加载。

registry proxy 本身是一个 nginx 服务器，它对矿工 API 执行 auth 子请求。参见 nginx 配置映射：https://github.com/rayonlabs/chutes-miner/blob/main/charts/templates/registry-cm.yaml

注入签名的矿工 API 代码位于：https://github.com/rayonlabs/chutes-miner/blob/main/api/registry/router.py

然后 nginx 将请求代理回相关的验证器（基于子域名中的 hotkey），验证器验证签名并将这些标头替换为可用于我们自托管 registry 的基本身份验证：https://github.com/rayonlabs/chutes-api/blob/main/api/registry/router.py

*__通过 helm 图表部署时，这会自动安装和配置__*

#### ⚡ API

每个矿工节点运行一个 API 服务，负责多种功能，包括：
- 服务器/库存管理
- 与验证器 API 的 websocket 连接
- Docker 镜像 registry 身份验证

*__通过 helm 图表部署时，这会自动安装和配置__*

#### 🧙‍♂️ Gepetto

Gepetto 是负责所有 Chute（即应用）管理的核心组件。除其他事项外，它还负责实际配置 Chute、扩展/缩减 Chute、尝试获取奖励等。

这是矿工需要优化的主要部分！


## 🚀 开始使用

### 1. 使用 Ansible 配置服务器

你首先要做的是配置服务器/Kubernetes。

所有服务器必须是裸机/VM，这意味着它在 Runpod、Vast 等平台上无法工作，并且我们目前不支持共享或动态 IP——IP 必须唯一、静态，并提供 1:1 端口映射。

### 重要内存注意事项！

每个 GPU 的 RAM（或非常接近）必须与显存一样多，这一点非常重要。例如，如果你使用的服务器有 4x A40 GPU（48GB 显存），则服务器必须有 >= 48 * 4 = 192 GB RAM！如果每个 GPU 的 RAM 没有至少与显存一样多，部署可能会失败，并且服务器无法被充分利用。

#### 重要存储注意事项！

一些提供商以不方便的方式挂载主存储，例如 latitude.sh 使用 RAID 1 时将卷挂载在 `/home`，hyperstack 挂载在 `/ephemeral` 等。在运行 ansible 脚本之前，请务必登录服务器并检查存储分配方式。如果你需要用于 huggingface 缓存、镜像等的存储空间，你需要确保尽可能多的空间分配在 `/var/snap` 下。你可以通过简单的绑定挂载来实现，例如，如果主存储在 `/home` 下，运行：
```bash
rsync -azv /var/snap/ /home/snap/
echo '/home/snap /var/snap none bind 0 0' >> /etc/fstab
mount -a
```
#### 重要网络注意事项！

开始之前，你必须禁用所有层级的防火墙（如果你喜欢冒险的话），或者启用以下设置：

- 允许 inventory 中所有节点之间的所有流量（所有端口、所有协议，包括 UDP）
- 在所有 GPU 节点上允许 Kubernetes 临时端口范围，因为 Chute 部署的端口将是随机的，在此范围内，并且需要公共可访问性 —— 默认端口范围是 30000-32767
- 允许从你管理/运行 chutes-miner add-node 等的任何机器访问 API 中的各种 nodePort 值，或者直接将其公开（特别重要的是 API node port，默认为 32000）

作为 wireguard 主节点的主 CPU 节点需要启用 IP 转发 —— 例如，如果你的节点在 GCP 中，你需要勾选一个启用 IP 转发的复选框。

你需要一台非 GPU 服务器（至少 8 核、64GB 内存），负责运行 postgres、redis、gepetto 和 API 组件（而非 Chutes），以及所有 GPU 服务器 😄（当然是开玩笑的，你可以使用任意数量的 GPU 服务器）

[支持的 GPU 列表可在此处找到](https://github.com/rayonlabs/chutes-api/blob/main/api/gpu.py)

前往 [ansible](ansible/README.md) 文档，了解设置裸机实例的步骤。确保更新 inventory.yml。
