#!/bin/bash
# 在已安装的 Debian 目标系统中执行（由 preseed late_command 调用）
set -e
cd /opt/EasyRouter
bash scripts/install.sh
systemctl enable easyrouter.service >/dev/null 2>&1 || true
