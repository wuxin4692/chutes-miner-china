# Node bootstrapping

To ensure the highest probability of success, you should provision your servers with `Ubuntu 22.04`, preferably with NO nvidia driver installations if possible.

## 1. Install ansible (on your local system, not the miner node(s))

### Mac

If you haven't yet, setup homebrew:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install ansible:
```bash
brew install ansible
```

### Ubuntu/Ubuntu (WSL)/aptitude based systems

```bash
sudo apt -y update && sudo apt -y install ansible python3-pip
```

### CentOS/RHEL/Fedora

Install epel repo if you haven't (and it's not fedora)
```bash
sudo dnf install epel-release -y
```

Install ansible:
```bash
sudo dnf install ansible -y
```

## 2. Install ansible collections

```bash
ansible-galaxy collection install community.general
ansible-galaxy collection install kubernetes.core
```

## 3. Update inventory configuration

Using your favorite text editor (vim of course), edit inventory.yml to suite your needs.

For example:
```yaml

all:
  vars:
    # List of SSH public keys, e.g. cat ~/.ssh/id_rsa.pub
    ssh_keys:
      - "ssh-rsa AAAA... user@hostname"
      - "ssh-rsa BBBB... user2@hostname2"
    # The username you want to use to login to those machines (and your public key will be added to).
    user: billybob
    # The initial username to login with, for fresh nodes that may not have your username setup.
    ansible_user: ubuntu
    # The default validator each GPU worker node will be assigned to.
    validator: 5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ
    # By default, no nodes are the primary (CPU node running all the apps, wireguard, etc.) Override this flag exactly once below.
    is_primary: false
    # We assume GPU is enabled on all nodes, but of course you need to disable this for the CPU nodes below.
    gpu_enabled: true
    # The port you'll be using for the registry proxy, MUST MATCH chart/values.yaml registry.service.nodePort!
    registry_port: 30500
    # SSH sometimes just hangs without this...
    ansible_ssh_common_args: '-o ControlPath=none'
    # SSH retries...
    ansible_ssh_retries: 3
    # Ubuntu major/minor version.
    ubuntu_major: "22"
    ubuntu_minor: "04"
    # CUDA version - leave as-is unless using h200s, in which case either use 12-5 or skip_cuda: true (if provider already pre-installed drivers)
    cuda_version: "12-6"
    # NVIDA GPU drivers - leave as-is unless using h200s, in which case it would be 555
    nvidia_version: "560"
    # Flag to skip the cuda install entirely, if the provider already has cuda 12.x+ installed (note some chutes will not work unless 12.6+)
    skip_cuda: false

  hosts:
    # This would be the main node, which runs postgres, redis, gepetto, etc.
    chutes-miner-cpu-0:
      ansible_host: 1.0.0.0
      external_ip: 1.0.0.0
      wireguard_ip: 192.168.0.1
      gpu_enabled: false
      is_primary: true

    # These are the GPU nodes, which actually run the chutes.
    chutes-miner-gpu-0:
      ansible_host: 1.0.0.1
      external_ip: 1.0.0.1
      wireguard_ip: 192.168.0.3
```

## 4. Connect networks via wireguard

```bash
ansible-playbook -i inventory.yml wireguard.yml
```

## 5. Bootstrap!

```bash
ansible-playbook -i inventory.yml site.yml
```

## 6. Join the kubernetes nodes together

If you have more than one host, make sure they are all part of the same cluster:
```bash
ansible-playbook -i inventory.yml join-cluster.yml
```

## 7. Install 3rd party helm charts

This step will install nvidia GPU operator and prometheus on your servers.

You need to run this one time only (although running it again shouldn't cause any problems).
```bash
ansible-playbook -i inventory.yml extras.yml
```

## To add a new node, after the fact

First, update your inventory.yml with the new host configuration.

Then, run the site playbook with `--limit {hostname}`, e.g.:
```bash
ansible-playbook -i inventory.yml site.yml --limit chutes-h200-0
```

Then, join the new node to the cluster (DO NOT USE `--limit` HERE!):
```bash
ansible-playbook -i inventory.yml join-cluster.yml
```
