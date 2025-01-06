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
    # This is your SSH public key, e.g. cat ~/.ssh/id_rsa.pub
    ssh_key: "ssh-rsa AAAA... user@hostnane"
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

## 4. Bootstrap!

```bash
ansible-playbook -i inventory.yml site.yml
```

## 5. Join the kubernetes nodes together

If you have more than one host, make sure they are all part of the same cluster:
```bash
ansible-playbook -i inventory.yml join-cluster.yml
```

## 6. Install 3rd party helm charts

This step will install nvidia GPU operator and prometheus on your servers.

You need to run this one time only!
```bash
ansible-playbook -i inventory.yml extras.yml
```

## To add a new node, after the fact

Be very careful, and make sure you note any and all changes before re-running the playbook for all hosts.  It should work well to add a new host, but be warned.
```bash
ansible-playbook -i inventory.yml site.yml
```

And join the node to the cluster:
```bash
ansible-playbook -i inventory.yml join-cluster.yml
```
