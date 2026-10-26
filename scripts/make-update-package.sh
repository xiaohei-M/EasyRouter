#!/bin/bash
# 生成易路由应用升级包（仅应用，不含 Debian 系统）
set -e
cd "$(dirname "$0")/.."
rm -f EasyRouter-update.zip
zip -r EasyRouter-update.zip easyrouter VERSION -x '*/__pycache__/*' -x '*.pyc'
echo "已生成：$(pwd)/EasyRouter-update.zip"
