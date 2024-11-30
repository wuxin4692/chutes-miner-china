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

### 2. Deploy the components via helm/kubectl

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

Then, make any modifications you'd like to the [values](chart/values.yaml) template.  You can then see exactly what your kubernetes deployment will look like with: `helm template . -f values.yaml`

#### XXX MORE TO COME
