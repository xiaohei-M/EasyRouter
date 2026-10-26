# syntax=docker/dockerfile:1
# 易路由 EasyRouter —— 容器化部署（实验性）
# 说明：软路由需要操作宿主机网络，容器必须以 host 网络 + 特权运行，
#       nftables / dnsmasq 实际作用于宿主机。
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        nftables \
        dnsmasq-base \
        iproute2 \
        isc-dhcp-client \
        ppp \
        conntrack \
        sshpass \
        procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/easyrouter
COPY easyrouter ./easyrouter

# 数据目录挂载点
VOLUME ["/etc/easyrouter", "/var/lib/easyrouter", "/var/log/easyrouter"]

EXPOSE 80 53/udp 53/tcp 67/udp

CMD ["/usr/bin/python3", "-m", "easyrouter", "run", \
     "--config", "/etc/easyrouter/config.json", "--data", "/var/lib/easyrouter"]
