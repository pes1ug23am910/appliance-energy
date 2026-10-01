#!/usr/bin/env bash
# Run with sudo on the temporary Ubuntu 24.04 lab, then reconnect via SSH.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 python3-venv python3-pip
systemctl enable --now docker
usermod -aG docker appliance
# Last-resort guest shutdown. The operator must also deallocate/delete in Azure:
# a guest shutdown alone does not release billable compute allocation.
systemd-run --unit=appliance-lab-deadline --on-active=90m /usr/sbin/shutdown -h now
