# Chutes miner

This repository contains all components related to mining on the chutes.ai permissionless, serverless, AI-centric compute platform.

We've tried to automate the bulk of the process via ansible, helm/kubernetes, so while it may seem like a lot, it should be fairly easy to get started.

## Component Overview

### Provisioning/management tools

#### Ansible

While not strictly necessary, we *highly* encourage all miners to use our provided [ansible](https://github.com/ansible/ansible) scripts to provision servers.
There are many nuances and requirements that are quite difficult to setup manually.

*More information on using the ansible scripts in subsequent sections.*

#### Kubernetes

The entirety of the chutes miner must run within a [kubernetes](https://kubernetes.io/)  While not strictly necessary, we recommend using microk8s (which is all handled automatically from the ansible scripts).
If you choose to not use microk8s, you must also modify or not use the provided ansible scripts.

### Miner Components

*There are many components and moving parts to the system, so before you do anything, please familiarize yourself with each!*

#### Postgres

We make heavy use of SQLAlchemy/postgres throughout chutes.  All servers, GPUs, deployments, etc., are tracked in postgresql which is deployed as a statefulset with a persistent volume claim within your kubernetes cluster.

#### Redis

Redis is primarily used for it's pubsub functionality within the miner.  Events (new chute added to validator, GPU added to the system, chute removed, etc.) trigger pubsub messages within redis, which trigger the various event handlers in code.

#### Porter

This component is an anti-(D)DoS mechanism - when you register as miner on chutes, this will serve as the public axon IP/port, and it's only purpose is to tell the validators where the *real* axon is.
Anyone attempting to DoS the axons will only take down the porters, and no harm will be done.

#### GraVal bootstrap

Chutes uses a custom c/CUDA library for validating graphics cards: https://github.com/rayonlabs/graval

The TL;DR is that it uses matrix multiplications seeded by device info to verify the authenticity of a GPU, including VRAM capacity tests (95% of total VRAM must be available for matrix multiplications).
All traffic sent to instances on chutes network are encrypted with keys that can only be decrypted by the GPU advertised.

When you add a new node to your kubernetes cluster, each GPU on the server must be verified with the GraVal package, so a bootstrap server is deployed to accomplish this (automatically, no need to fret).

#### API

Each miner runs an API service, which does a variety of things including:
- server/inventory management
- websocket connection to the validator API
- docker image registry authentication

#### Gepetto

Gepetto is the key component responsible for all chute (aka app) management. Among other things, it is responsible for actually provisioning chutes, scaling up/down chutes, attempting to claim bounties, etc.

This is the main thing to optimize as a miner!

## Getting Started

### 1. Use ansible to provision servers

The first thing you'll want to do is provision your servers/kubernetes.

ALL servers must be bare metal/VM, meaning it will not work on Runpod, Vast, etc.

You'll need a bare minimum of one non-GPU server responsible for running postgres, redis, gepetto, and API components (not chutes), although we'd recommend more than one, and __*ALL*__ of the GPU servers 😄

Head over to the [ansible](ansible/README.md) documentation for steps on setting up your bare metal instances.  Be sure to update inventory.yml 

### 2. Configure prerequisites

Once you've configured your kubernetes cluster, you can get the kubernetes configuration from the primary server (whichever server you labeled as primary in `ansible/inventory.yml`) from `/home/{username}/.kube/config`

Alternatively you can login to the primary server and run:
```bash
microk8s config
```

Install kubectl on your local machine, or whichever machine you plan to manage your miner from (which can be but likely isn't one of the servers you just deployed, personally I use a laptop for this): https://kubernetes.io/docs/reference/kubectl/

Then copy the the kubernetes configuration you just found above into your local machine `~/.kube/config`

You'll need to setup a few things manually:
- Create a docker hub login to avoid getting rate-limited on pulling public images (you may not need this at all, but it can't hurt):
  - Head over to https://hub.docker.com/ and sign up, generate a new personal access token for public read-only access, then create the secret: `kubectl create secret docker-registry regcred --docker-server=docker.io --docker-username=[repalce with your username] --docker-password=[replace with your access token] --docker-email=[replace with your email]`
- Create the miner credentials
  - You'll need to find the ss58Address and secretSeed from the hotkey file you'll be using for mining, e.g. `cat ~/.bittensor/wallets/default/hotkeys/hotkey`
  - `kubectl create secret generic miner-credentials --from-literal=ss58=[replace with ss58Address value] --from-literal=seed=[replace with secretSeed value, removing '0x' prefix] -n chutes`
 
Install helm on the same local/management machine: https://helm.sh/docs/intro/install/

### 3. Configure your environment

Be sure to thoroughly examine [values](chart/values.yaml) and update according to your particular environment.

Primary sections to update:

#### a. validators

Unlike most subnets, the validators list for chutes must be explicitly configured rather than relying on the metagraph.
Due to the extreme complexity and high expense of operating a validator on this subnet, we're hoping most validators will opt to use the child hotkey functionality rather that operating their own validators.

To that end, any validators you wish to support MUST be configured in the top-level validators section:

The dev/testnet configuration is as follows:
```yaml
validators:
  defaultRegistry: registry.chutes.dev:5000
  defaultApi: https://api.chutes.dev
  supported:
    - hotkey: 5DCJTfVx3ReNyxW3SgQEKFgvXFuqnK3BNW1vMhTQK4jdZbV4
      registry: registry.chutes.dev:5000
      api: https://api.chutes.dev
      socket: ws://ws.chutes.dev:8080
```

The mainnet configuration is TBD, but in any case you'll need to explicitly enumerate the validators that are supported by your miner, in the `supported` section.

#### b. huggingface model cache

To enable faster cold-starts, the kubernetes deployments use a hostPath mount for caching huggingface models.  The default is set to purge anything over 7 days old, when > 500gb has been consumed:
```yaml
hfCache:
  maxAgeDays: 7
  maxSizeGB: 500
```

If you have lots and lots of storage space, you may want to increase this or otherwise change defaults.


#### c. porter

If you wish to use porter for (D)DoS protection, you'll want to configure this section.
```yaml
porter:
  enabled: true
  real_host: 1.2.3.4
  real_port: 32000
  service:
    type: NodePort
    port: 8000
    targetPort: 8000
    nodePort: 31000
    ...
```
The `real_host` value will be the IP address of your non-GPU primary kubernetes node (can also be a DNS name if you want to use multiple IPs or load balancer or whatever, but must be http/plain-text).

The `real_port` will need to be within your kubernetes nodePort range which by default is something like 30000-32767, and will match the nodePort value you specify for minerApi.

The other key is the `annotations` block, which by default looks for a node within your cluster labeled as `chutes-porter="true"`
```yaml
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: chutes-porter
            operator: In
            values:
              - "true"
```

You'll need to manually apply the annotation to that node, e.g.: `kubectl label node foobar-server-0 chutes-porter=true`

#### d. minerApi

The defaults should do fairly nicely here, but you may want to tweak the service, namely nodePort, to play nicely with porter:
```yaml
minerApi:
  ...
  service:
    nodePort: 32000
    ...
```

#### e. other

Feel free to adjust redis/postgres/etc. as you wish, but probably not necessary.

### 4. Update gepetto with your optimized strategy

Gepetto is the most important component as a miner.  It is responsible for selecting chutes to deploy, scale up, scale down, delete, etc.
You'll want to thoroughly examine this code and make any changes that you think would gain you more total compute time.

Once you are satisfied with the state of the `gepetto.py` file, you'll need to create a configmap object in kubernetes that stores your file:
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

Personally, I love helm charts but don't actually like installing the charts as such.  A sane person would use the `helm install` command: https://helm.sh/docs/helm/helm_install/

Or, if you're like me, you can run something like this, from within the `charts` directory:
```bash
helm template . -f values.yaml > miner-charts.yaml
```

Then, you can examine the chart values to see exactly how your modifications to the values file manifest.  If you are satisfied with the result, you can then deploy:
```bash
kubectl apply -f miner-charts.yaml -n chutes
```
