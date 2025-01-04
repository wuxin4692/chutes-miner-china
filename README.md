# Chutes miner

This repository contains all components related to mining on the chutes.ai permissionless, serverless, AI-centric compute platform.

We've tried to automate the bulk of the process via ansible, helm/kubernetes, so while it may seem like a lot, it should be fairly easy to get started.

## 📋 Table of Contents

- [TL;DR](#%EF%B8%8F-tldr)
- [Component Overview](#-component-overview)
   - [Provisioning/Management Tools](#%EF%B8%8F-provisioningmanagement-tools)
     - [Ansible](#-ansible)
     - [Wireguard](#-wireguard)
     - [Kubernetes](#%EF%B8%8F-kubernetes)
   - [Miner Components](#-miner-components)
     - [Postgres](#-postgres)
     - [Redis](#-redis)
     - [GraVal Bootstrap](#-graval-bootstrap)
     - [Regstry Proxy](#-registry-proxy)
     - [Squid Proxy](#-squid-proxy)
     - [API](#-api)
     - [Gepetto](#%EF%B8%8F-gepetto)
- [Getting Started](#-getting-started)
   - [Use Ansible to Provision Servers](#1-use-ansible-to-provision-servers)
   - [Configure Prerequisites](#2-configure-prerequisites)
   - [Configure Your Environment](#3-configure-your-environment)
   - [Update Gepetto with Your Optimized Strategy](#4-update-gepetto-with-your-optimized-strategy)
   - [Deploy the Miner within Your Kubernetes Cluster](#5-deploy-the-miner-within-your-kubernetes-cluster)
   - [Register](#6-register)

## ⛏️ TL;DR

The goal of mining on chutes is to provide as much compute as possible, optimizing for cold start times (running new applications or applications that have been preempted). Everything is automated with kubernetes, and coordinated by the `gepetto.py` script to optimize for cost efficiency and maximize your share of compute.

Incentives are based on total compute time (including bounties give from being first to provide inference on code app).

You should probably run a wide variety of GPUs, from very cheap (a10, a5000, t4, etc.) to very powerful (8x h100 nodes).

Never register more than one UID, since it will just reduce your total compute time and you'll compete with yourself pointlessly.  Just add capacity to one miner.

Incentives/weights are calculated from 7 day sum of compute, so be patient when you start mining.  We want high quality, stable miners in it for the long haul!

## 🔍 Component Overview

### 🛠️ Provisioning/management tools

#### 🤖 Ansible

While not strictly necessary, we *highly* encourage all miners to use our provided [ansible](https://github.com/ansible/ansible) scripts to provision servers.
There are many nuances and requirements that are quite difficult to setup manually.

*More information on using the ansible scripts in subsequent sections.*

#### 🔒 Wireguard

Wireguard is a fast, secure VPN service that is created by ansible provisioning, which allows your nodes to communicate when they are not all on the same internal network.

It is often the case that you'll want CPU instances on one provider (AWS, Google, etc.), and GPU instances on another (Latitude, Massed Compute, etc.), and you may have several providers for each due to inventory.

By installing Wireguard, your kubernetes cluster can span any number of providers without issue.

*__this is installed and configured automatically by ansible scripts__*

#### ☸️ Kubernetes

The entirety of the chutes miner must run within a [kubernetes](https://kubernetes.io/)  While not strictly necessary, we recommend using microk8s (which is all handled automatically from the ansible scripts).
If you choose to not use microk8s, you must also modify or not use the provided ansible scripts.

*__this is installed and configured automatically by ansible scripts__*

### 🧩 Miner Components

*There are many components and moving parts to the system, so before you do anything, please familiarize yourself with each!*

#### 🐘 Postgres

We make heavy use of SQLAlchemy/postgres throughout chutes.  All servers, GPUs, deployments, etc., are tracked in postgresql which is deployed as a statefulset with a persistent volume claim within your kubernetes cluster.

*__this is installed and configured automatically when deploying via helm charts__*

#### 🔄 Redis

Redis is primarily used for it's pubsub functionality within the miner.  Events (new chute added to validator, GPU added to the system, chute removed, etc.) trigger pubsub messages within redis, which trigger the various event handlers in code.

*__this is installed and configured automatically when deploying via helm charts__*

#### ✅ GraVal bootstrap

Chutes uses a custom c/CUDA library for validating graphics cards: https://github.com/rayonlabs/graval

The TL;DR is that it uses matrix multiplications seeded by device info to verify the authenticity of a GPU, including VRAM capacity tests (95% of total VRAM must be available for matrix multiplications).
All traffic sent to instances on chutes network are encrypted with keys that can only be decrypted by the GPU advertised.

When you add a new node to your kubernetes cluster, each GPU on the server must be verified with the GraVal package, so a bootstrap server is deployed to accomplish this (automatically, no need to fret).

Each time a chute starts/gets deployed, it also needs to run GraVal to calculate the decryption key that will be necessary for the GPU(s) the chute is deployed on.

*__this is done automatically__*

#### 🔀 Registry proxy

In order to keep the chute docker images somewhat private (since not all images are public), we employ a registry proxy on each miner that injects authentication via bittensor key signature.

Each docker image appears to kubelet as `[validator hotkey ss58].localregistry.chutes.ai:30500/[image username]/[image name]:[image tag]`

This subdomain points to 127.0.0.1 so it always loads from the registry service proxy on each GPU server via NodePort routing and local first k8s service traffic policy.

The registry proxy itself is an nginx server that performs an auth subrequest to the miner API.  See the nginx configmap: https://github.com/rayonlabs/chutes-miner/blob/main/charts/templates/registry-cm.yaml

The miner API code that injects the signatures is here: https://github.com/rayonlabs/chutes-miner/blob/main/api/registry/router.py

Nginx then proxies the request upstream back to the validator in question (based on the hotkey as part of the subdomain), which validates the signatures and replaces those headers with basic auth that can be used with our self-hosted registry: https://github.com/rayonlabs/chutes-api/blob/main/api/registry/router.py

*__this is installed and configured automatically when deploying via helm charts__*

#### 🦑 Squid proxy

In order to prevent some amount of abuse of the platform, chutes are limited to HTTPS traffic, and only through a squid proxy. The squid proxy server does not currently cache, rather it's used to filter the list of upstream domains the chutes are allowed to connect to, e.g. huggingface, S3, etc.

The list of allowed domains will change over time, but can be found in the configmap within the charts directory [here](/charts/templates/squid-cm.yaml)

*__this is installed and configured automatically when deploying via helm charts__*

#### ⚡ API

Each miner runs an API service, which does a variety of things including:
- server/inventory management
- websocket connection to the validator API
- docker image registry authentication

*__this is installed and configured automatically when deploying via helm charts__*

#### 🧙‍♂️ Gepetto

Gepetto is the key component responsible for all chute (aka app) management. Among other things, it is responsible for actually provisioning chutes, scaling up/down chutes, attempting to claim bounties, etc.

This is the main thing to optimize as a miner!

## 🚀 Getting Started

### 1. Use ansible to provision servers

The first thing you'll want to do is provision your servers/kubernetes.

ALL servers must be bare metal/VM, meaning it will not work on Runpod, Vast, etc.

#### Important storage note!

Some providers mount the primary storage in inconvient ways, e.g. latitude.sh when using raid 1 mounts the volume on `/home`, hyperstack mounts under `/ephemeral`, etc.  Before running the ansible scripts, be sure to login to your servers and check how the storage is allocated.  If you want storage space for huggingface cache, images, etc., you'll want to be sure as much as possible is allocated under `/var/snap`.
You can do this with a simple bind mount, e.g. if the main storage is under `/home`, run:
```bash
rsync -azv /var/snap/ /home/snap/
echo '/home/snap /var/snap none bind 0 0' >> /etc/fstab
mount -a
```

You'll need one non-GPU server (8 cores, 64gb ram minimum) responsible for running postgres, redis, gepetto, and API components (not chutes), and __*ALL*__ of the GPU servers 😄 (just kidding of course, you can use as many or as few as you wish)

[The list of supported GPUs can be found here](https://github.com/rayonlabs/chutes-api/blob/main/api/gpu.py)

Head over to the [ansible](ansible/README.md) documentation for steps on setting up your bare metal instances.  Be sure to update inventory.yml

### 2. Configure prerequisites

Once you've provisioned your nodes with ansible and have kubernetes running, you can get the kubernetes configuration from the primary server (whichever server you labeled as primary in `ansible/inventory.yml`) from `/home/{username}/.kube/config`

Alternatively you can login to the primary server and run:
```bash
microk8s config
```

The easiest way to interact with kubernetes would be from within the primary node, but you can alternatively set it up on your local machine or other server.  To do so:
- install [kubectl](https://kubernetes.io/docs/reference/kubectl/)
- copy the the kubernetes configuration from previous step to that machine at path `~/.kube/config`
- replace the IP address of the cluster with the public IP address of the primary node
- since the IP will not match the cert, you will need to specify `--insecure-skip-tls-verify` when running any kubectl commands from this server (not necessary when done on primary node)

If you plan to use the primary node, you should alias `kubectl` to be `microk8s kubectl`, e.g. `echo 'alias kubectl="microk8s kubectl"' >> .bashrc`

And while you're at it, alias `helm` as well, e.g. `echo 'alias helm="microk8s helm"' >> .bashrc`

You'll need to setup a few things manually:
- Create a docker hub login to avoid getting rate-limited on pulling public images (you may not need this at all, but it can't hurt):
  - Head over to https://hub.docker.com/ and sign up, generate a new personal access token for public read-only access, then create the secret:
```
kubectl create secret docker-registry regcred --docker-server=docker.io --docker-username=[repalce with your username] --docker-password=[replace with your access token] --docker-email=[replace with your email]
```
- Create the miner credentials
  - You'll need to find the ss58Address and secretSeed from the hotkey file you'll be using for mining, e.g. `cat ~/.bittensor/wallets/default/hotkeys/hotkey`
```
kubectl create secret generic miner-credentials \
  --from-literal=ss58=[replace with ss58Address value] \
  --from-literal=seed=[replace with secretSeed value, removing '0x' prefix] \
  -n chutes
```

Install helm on the same local/management machine: https://helm.sh/docs/intro/install/

### 3. Configure your environment

Be sure to thoroughly examine [values](chart/values.yaml) and update according to your particular environment.

Primary sections to update:

#### a. validators

Unlike most subnets, the validators list for chutes must be explicitly configured rather than relying on the metagraph.
Due to the extreme complexity and high expense of operating a validator on this subnet, we're hoping most validators will opt to use the child hotkey functionality rather that operating their own validators.

To that end, any validators you wish to support MUST be configured in the top-level validators section:

The default mainnet configuration is:
```yaml
validators:
  defaultRegistry: registry.chutes.ai
  defaultApi: https://api.chutes.ai
  supported:
    - hotkey: 5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ
      registry: registry.chutes.ai
      api: https://api.chutes.ai
      socket: wss://ws.chutes.ai
```

#### b. huggingface model cache

To enable faster cold-starts, the kubernetes deployments use a hostPath mount for caching huggingface models.  The default is set to purge anything over 7 days old, when > 500gb has been consumed:
```yaml
hfCache:
  maxAgeDays: 7
  maxSizeGB: 500
```

If you have lots and lots of storage space, you may want to increase this or otherwise change defaults.


#### c. minerApi

The defaults should do fairly nicely here, but you may want to tweak the service, namely nodePort, if you want to change ports.
```yaml
minerApi:
  ...
  service:
    nodePort: 32000
    ...
```

#### d. other

Feel free to adjust redis/postgres/etc. as you wish, but probably not necessary.

### 4. Update gepetto with your optimized strategy

Gepetto is the most important component as a miner.  It is responsible for selecting chutes to deploy, scale up, scale down, delete, etc.
You'll want to thoroughly examine this code and make any changes that you think would gain you more total compute time.

Once you are satisfied with the state of the `gepetto.py` file, you'll need to create a configmap object in kubernetes that stores your file (from inside the `chutes-miner` directory, from cloning repo):
```bash
kubectl create configmap gepetto-code --from-file=gepetto.py -n chutes
```

Any time you wish to make further changes to gepetto, you can either delete and re-create:
```bash
kubectl delete configmap gepetto-code -n chutes
kubectl create configmap gepetto-code --from-file=gepetto.py -n chutes
```

Or use some fanciness:
```bash
kubectl create configmap gepetto-code --from-file=gepetto.py -o yaml --dry-run=client | kubectl apply -n chutes -f -
```

### 5. Deploy the miner within your kubernetes cluster

First, and __*exactly one time*__, you'll want to generate passwords for postgres and redis - __*never run this more than once or things will break!*__
Execute this from the `charts` directory:
```bash
helm template . --set createPasswords=true -s templates/one-time-passwords.yaml | kubectl apply -n chutes -f -
```

Personally, I love helm charts but don't actually like installing the charts as such.  A sane person would use the `helm install` command: https://helm.sh/docs/helm/helm_install/

Or, if you're like me, you can run something like this, from within the `charts` directory:
```bash
helm template . -f values.yaml > miner-charts.yaml
```

Then, you can examine the chart values to see exactly how your modifications to the values file manifest.  If you are satisfied with the result, you can then deploy:
```bash
kubectl apply -f miner-charts.yaml -n chutes
```

### 6. Register

Register as a miner on subnet 64.
```bash
btcli subnet register --netuid 64 --wallet.name [COLDKEY] --wallet.hotkey [HOTKEY]
```

You __*should not*__ announce an axon here!  All communications are done via client-side initialized socket.io connections so public axons serve no purpose and are just a security risk.


### 7. Add your GPU nodes to inventory

The last step in enabling a GPU node in your miner is to use the `add-node` command in the `chutes-miner` CLI.  This calls the miner API, triggers spinning up graval validation services, etc.  This must be run exactly once for each GPU node in order for them to be usable by your miner.

Make sure you install `chutes-miner-cli` package (you can do this on the CPU node, your laptop, wherever):
```bash
pip install chutes-miner-cli
```

Run this for each GPU node in your inventory:
```bash
chutes-miner add-node \
  --name [SERVER NAME FROM inventory.yaml] \
  --validator [VALIDATOR HOTKEY] \
  --hourly-cost [HOURLY COST] \
  --gpu-short-ref [GPU SHORT IDENTIFIER] \
  --hotkey [~/.bittensor/wallets/[COLDKEY]/hotkeys/[HOTKEY] \
  --miner-api http://[MINER API SERVER IP]:[MINER API PORT]
```

- `--name` here corresponds to the short name in your ansible inventory.yaml file, it is not the entire FQDN.
- `--validator` is the hotkey ss58 address of the validator that this server will be allocated to
- `--hourly-cost` is how much you are paying hourly for this server; part of the optimization strategy in gepetto is to minimize cost when selecting servers to deploy chutes on
- `--gpu-short-ref` is a short identifier string for the type of GPU on the server, e.g. `a6000`, `l40s`, `h100_sxm`, etc.  See supported GPUs here: https://github.com/rayonlabs/chutes-api/blob/c0df10cff794c17684be9cf1111c00d84eb015b0/api/gpu.py#L17
- `--hotkey` is the path to the hotkey file you registered with, used to sign requests to be able to manage inventory on your system via the miner API
- `--miner-api` is the base URL to your miner API service, which will be http://[non-GPU node IP]:[minerAPI port, default 32000], i.e. find the public/external IP address of your CPU-only node, and whatever port you configured for the API service (which is 32000 if you didn't change the default).

You can add additional GPU nodes at any time by simply updating inventory.yaml and rerunning the `site.yaml` and `join-cluster.yaml` playbooks: [ansible readme](/ansible/README.md#to-add-a-new-node-after-the-fact)
