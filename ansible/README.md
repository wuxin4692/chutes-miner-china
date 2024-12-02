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

### Ubuntu/aptitude based systems

```bash
sudo apt update && apt -y install -y ansible python3-pip
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

Using your favorite text editor (vim of course), edit inventory.yml to include your servers.

For example:
```yaml
all:
  hosts:
    chutes-dev-1:
      ansible_host: 1.2.3.4
      ansible_user: ubuntu
      user: billybob
      gpu_enabled: true
      ssh_key: "ssh-rsa AAAA... billybob@machine"
```

In this case:
- `chutes-dev-1` is the hostname
- `1.2.3.4` is the IP address of the server
- `ubuntu` is the *initial* username, i.e. when the node is provisioned for you by your server provider, the initial login username
- `billybob` is the user you'd like to create and login as
- `gpu_enabled` indicates whether this is a GPU node or not (database, API, etc. services should likely run on non-GPU nodes)
- `ssh_key` is the public key, e.g. contents of `~/.ssh/id_rsa.pub`

## 4. Bootstrap!

```bash
ansible-playbook -i inventory.yml site.yml
```

## 5. Join the kubernetes nodes together

If you have more than one host, you'll want to join all of the secondary nodes to the primary.
```bash
ansible-playbook -i inventory.yml join-cluster.yml
```

## 6. Enable NVidia GPU operator

You need to run this one time only!
```bash
ansible-playbook -i inventory.yml nvidia.yaml
```

## 7. Adding a new node (carefully!)

It could be very detrimental to re-run the entire playbook against all hosts, so you're best bet is to apply the playbook with `--limit new-hostname`, e.g.:
```bash
ansible-playbook -i inventory.yml site.yml --limit new-hostname
```

Then, manually run this on the primary kubernetes node:
```bash
microk8s add-node
```

Then, run that join command on the new host!
