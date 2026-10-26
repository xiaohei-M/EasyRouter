#!/usr/bin/env bash
# ============================================================
#  易路由 EasyRouter 一键卸载脚本
#  用法:  sudo bash uninstall.sh
# ============================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 权限运行：sudo bash uninstall.sh"
  exit 1
fi

read -r -p "确认卸载 易路由 EasyRouter？（配置与设备数据将一并删除）[y/N] " ans
if [[ "${ans,,}" != "y" ]]; then
  echo "已取消。"
  exit 0
fi

echo "停止并移除服务…"
systemctl disable --now easyrouter >/dev/null 2>&1 || true
rm -f /etc/systemd/system/easyrouter.service
rm -f /etc/sysctl.d/99-easyrouter.conf

echo "清理 nftables 规则…"
nft delete table inet easyrouter >/dev/null 2>&1 || true

echo "删除程序与数据…"
rm -rf /opt/easyrouter
rm -rf /etc/easyrouter
rm -rf /var/lib/easyrouter
rm -rf /var/log/easyrouter
rm -rf /var/run/easyrouter

systemctl daemon-reload
echo ""
echo "卸载完成。依赖软件包（dnsmasq-base、nftables 等）保留未动，"
echo "如需一并移除可执行: apt-get purge -y dnsmasq-base nftables isc-dhcp-client ppp conntrack"
