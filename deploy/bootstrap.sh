#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 VPS for GraphRecall. Run from your machine:
#
#   ssh root@<server-ip> 'bash -s' < deploy/bootstrap.sh
#
# Then copy the stack and fill in secrets (see RUNBOOK.md):
#   scp deploy/compose.prod.yml deploy/Caddyfile deploy/backup.sh deploy/restore.sh deploy@<ip>:/opt/graphrecall/
#   ssh deploy@<ip> 'nano /opt/graphrecall/.env'
#
# Idempotent: safe to run again.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg ufw fail2ban unattended-upgrades

# Docker Engine from Docker's apt repository (not the convenience script)
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Security updates applied automatically; firewall allows SSH and HTTPS only
dpkg-reconfigure -f noninteractive unattended-upgrades
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
systemctl enable --now fail2ban

# Unprivileged deploy user, with the same SSH keys as root
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --groups docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
if [[ -f /root/.ssh/authorized_keys ]]; then
  install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
fi
# Key-only SSH: no passwords, no root login
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd || true

# App directory and secrets file (owner-only)
install -d -m 750 -o deploy -g deploy /opt/graphrecall
if [[ ! -f /opt/graphrecall/.env ]]; then
  install -m 600 -o deploy -g deploy /dev/null /opt/graphrecall/.env
  echo "created empty /opt/graphrecall/.env: fill it from deploy/env.prod.example"
fi

# Nightly backup at 03:00 UTC
cat > /etc/cron.d/graphrecall-backup <<'CRON'
0 3 * * * deploy set -a; . /opt/graphrecall/.env; set +a; /opt/graphrecall/backup.sh >> /opt/graphrecall/backup.log 2>&1
CRON
chmod 644 /etc/cron.d/graphrecall-backup

echo "bootstrap complete: docker $(docker --version | cut -d' ' -f3), firewall on, deploy user ready"
