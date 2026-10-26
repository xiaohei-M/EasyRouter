#!/usr/bin/env bash
# ============================================================
#  易路由 EasyRouter 一键安装脚本（Debian 11+/Ubuntu 20.04+）
#  用法:  sudo bash install.sh
# ============================================================
set -euo pipefail

APP_NAME="易路由 EasyRouter"
INSTALL_DIR="/opt/easyrouter"
CONF_DIR="/etc/easyrouter"
DATA_DIR="/var/lib/easyrouter"
LOG_DIR="/var/log/easyrouter"
RUN_DIR="/var/run/easyrouter"
SERVICE="easyrouter.service"

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 权限运行：sudo bash install.sh"
  exit 1
fi

echo "============================================="
echo "  ${APP_NAME} 一键安装"
echo "============================================="

# ---------- 1. 安装依赖 ----------
echo "[1/6] 安装系统依赖（python3 nftables dnsmasq-base iproute2 dhclient ppp conntrack sshpass）…"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 nftables dnsmasq-base iproute2 isc-dhcp-client ppp conntrack sshpass
else
  echo "错误：未找到 apt-get，仅支持 Debian/Ubuntu 系列发行版。"
  exit 1
fi

# ---------- 2. 复制程序 ----------
echo "[2/6] 安装程序到 ${INSTALL_DIR} …"
mkdir -p "${INSTALL_DIR}" "${CONF_DIR}" "${DATA_DIR}" "${LOG_DIR}" "${RUN_DIR}"
if [[ -d "./easyrouter" ]]; then
  # 从源码目录安装
  cp -rf ./easyrouter "${INSTALL_DIR}/"
  SRC_DIR="$(pwd)"
else
  # 从已安装目录升级
  SRC_DIR="${INSTALL_DIR}"
fi
if [[ -f "${SRC_DIR}/VERSION" ]]; then
  cp -f "${SRC_DIR}/VERSION" "${INSTALL_DIR}/VERSION"
fi
chmod 644 "${INSTALL_DIR}/easyrouter/web"/*.* 2>/dev/null || true

# ---------- 3. systemd 服务 ----------
echo "[3/6] 写入 systemd 服务单元…"
cat > "/etc/systemd/system/${SERVICE}" <<EOF
[Unit]
Description=易路由 EasyRouter —— 全中文软路由系统
Documentation=https://example.invalid/easyrouter
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 -m easyrouter run --config ${CONF_DIR}/config.json --data ${DATA_DIR}
ExecStopPost=/bin/true
Restart=always
RestartSec=3
StandardOutput=append:${LOG_DIR}/easyrouter.log
StandardError=append:${LOG_DIR}/easyrouter.log

[Install]
WantedBy=multi-user.target
EOF

# ---------- 4. 内核参数 ----------
echo "[4/6] 开启 IP 转发与连接跟踪计费…"
cat > /etc/sysctl.d/99-easyrouter.conf <<EOF
# 由易路由自动生成
net.ipv4.ip_forward = 1
net.netfilter.nf_conntrack_acct = 1
net.netfilter.nf_conntrack_max = 131072
EOF
sysctl -p /etc/sysctl.d/99-easyrouter.conf >/dev/null 2>&1 || true

# ---------- 5. 服务管理 ----------
echo "[5/6] 启用服务…"
systemctl daemon-reload
systemctl enable "${SERVICE}" >/dev/null 2>&1 || true

# 若系统自带 dnsmasq 服务占用端口，予以停用（本系统自行管理 dnsmasq 进程）
if systemctl list-unit-files 2>/dev/null | grep -q "^dnsmasq.service"; then
  echo "      检测到系统 dnsmasq 服务，将其停用（由易路由统一管理）…"
  systemctl disable --now dnsmasq >/dev/null 2>&1 || true
fi

# ---------- 6. 完成 ----------
echo "[6/6] 安装完成！"
echo ""
echo "  接下来："
echo "  1) 交互式配置向导:  sudo python3 -m easyrouter setup   （在 ${INSTALL_DIR} 目录下）"
echo "     或直接启动后在浏览器中完成安装向导:"
echo "     sudo systemctl start easyrouter"
echo "     然后访问 http://<本机IP> 完成安装向导"
echo "  2) 常用命令:"
echo "     systemctl status easyrouter   查看状态"
echo "     systemctl restart easyrouter  重启服务"
echo "     journalctl -u easyrouter -f   查看日志"
echo ""
echo "  卸载: sudo bash ${INSTALL_DIR}/scripts/uninstall.sh 或 sudo bash uninstall.sh"
