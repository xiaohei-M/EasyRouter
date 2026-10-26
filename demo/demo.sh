#!/usr/bin/env bash
# 易路由 EasyRouter —— 演示模式一键启动
cd "$(dirname "$0")/.."
python3 -m easyrouter demo --port 8080
