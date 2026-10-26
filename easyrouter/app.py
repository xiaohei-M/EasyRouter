# -*- coding: utf-8 -*-
"""应用装配：配置/存储/认证/后端/监控/HTTP 服务。"""
import copy
import logging
import os
import platform
import threading
import time
from collections import deque

from . import VERSION
from . import api as api_mod
from . import auth as auth_mod
from . import config as config_mod
from . import core
from . import gateways as gateways_mod
from . import httpd as httpd_mod
from . import leases as leases_mod
from . import monitor as monitor_mod
from . import store as store_mod


class RingHandler(logging.Handler):
    """把日志同时写入内存环形缓冲，供“系统日志”页面展示。"""

    def __init__(self, buf):
        super().__init__()
        self.buf = buf

    def emit(self, record):
        try:
            self.buf.append(self.format(record))
        except Exception:
            pass


class App:
    def __init__(self, config_path, data_dir, log, demo=False):
        self.conf_path = config_path
        self.data_dir = data_dir
        self.log = log
        self.demo = demo
        self.cfg, state = config_mod.load(config_path)
        if state.startswith("error"):
            log.warning("配置读取失败（%s），使用默认配置", state)
        self.store = store_mod.Store(os.path.join(data_dir, "easyrouter.db"))
        self.auth = auth_mod.SessionManager()
        self.limiter = auth_mod.LoginLimiter()
        if demo:
            self._prepare_demo()
        self.backend = core.create_backend("demo" if demo else "linux", log=log)
        self.monitor = monitor_mod.Monitor(self.cfg, self.backend, self.store, log)
        self.gateway_mgr = gateways_mod.GatewayManager(self.cfg, log, demo=demo)
        self.lease_binder = leases_mod.LeaseBinder(self)
        self.config_lock = threading.RLock()
        self.router = httpd_mod.Router()
        self.server = None
        self.log_tail = deque(maxlen=400)
        self.client_errors = deque(maxlen=50)
        ring = RingHandler(self.log_tail)
        ring.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(ring)
        api_mod.register(self)

    def _prepare_demo(self):
        """演示模式：自动完成初始化，初始密码 admin123，并预置三台上游网关。"""
        if not self.cfg.get("setup_done"):
            self.cfg = config_mod.deep_merge(self.cfg, {
                "setup_done": True,
                "admin": {"password_hash": auth_mod.hash_password("admin123"), "username": "admin"},
                "network": {
                    "wan": {"interface": "wan0", "mode": "none"},
                    "lan": {"interface": "lan0", "ip": "192.168.1.1", "netmask": "255.255.255.0"},
                },
                "web": {"host": "127.0.0.1", "port": 8080, "lan_only": False},
            })
        if not self.cfg.get("gateways"):
            self.cfg["gateways"] = [
                {"id": "gw-telecom", "name": "电信宽带 · 光猫", "ip": "192.168.10.1",
                 "method": "demo"},
                {"id": "gw-unicom", "name": "联通宽带 · 路由器", "ip": "192.168.20.1",
                 "method": "demo"},
                {"id": "gw-mobile", "name": "移动宽带 · 路由器", "ip": "192.168.30.1",
                 "method": "demo"},
            ]
        config_mod.save(self.conf_path, self.cfg)

    def start(self):
        """启动监控线程与 HTTP 服务。返回 (host, port)。"""
        self.monitor.start()
        self.gateway_mgr.start()
        self.lease_binder.start()
        web = self.cfg.get("web", {})
        host = web.get("host") or "0.0.0.0"
        port = int(web.get("port") or 80)
        try:
            self.server = httpd_mod.AppServer((host, port), self)
        except OSError as e:
            if port < 1024 and "permission" in str(e).lower():
                raise SystemExit(
                    "绑定 %s:%d 失败：1024 以下端口需要 root 权限。请以 root 运行，"
                    "或修改配置中的 web.port（例如 8080）。" % (host, port))
            raise SystemExit("绑定 %s:%d 失败：%s" % (host, port, e))
        return host, port

    def serve_forever(self):
        self.server.serve_forever()

    def stop(self):
        try:
            self.lease_binder.stop()
        except Exception:
            pass
        try:
            self.gateway_mgr.stop()
        except Exception:
            pass
        try:
            self.monitor.stop()
        except Exception:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            try:
                self.server.server_close()
            except Exception:
                pass

    # 保存并应用配置（供设置 API 与自动绑定复用）
    def update_config(self, new_cfg):
        with self.config_lock:
            old = self.cfg
            config_mod.save(self.conf_path, new_cfg)
            self.cfg = new_cfg
            self.monitor.update_cfg(new_cfg)
            self.gateway_mgr.update_cfg(new_cfg)
            errors, warnings, applied = self.backend.apply(old, new_cfg)
            return errors, warnings, applied

    # 导出/恢复备份
    def export_backup(self):
        with self.config_lock:
            with self.monitor.lock:
                totals = {ip: [int(v[0]), int(v[1])] for ip, v in self.monitor.totals.items()}
            return {
                "format": "easyrouter-backup",
                "version": VERSION,
                "created": int(time.time()),
                "config": copy.deepcopy(self.cfg),
                "aliases": self.store.get_aliases(),
                "totals": totals,
            }

    def restore_backup(self, data):
        if not isinstance(data, dict) or data.get("format") != "easyrouter-backup":
            return False, ["不是易路由备份文件"]
        cfg = data.get("config")
        if not isinstance(cfg, dict):
            return False, ["备份中缺少配置数据"]
        new = config_mod.deep_merge(config_mod.new_default(), cfg)
        errors, _warnings = config_mod.validate(new)
        if errors:
            return False, errors
        with self.config_lock:
            old = self.cfg
            config_mod.save(self.conf_path, new)
            self.cfg = new
            self.monitor.update_cfg(new)
            self.gateway_mgr.update_cfg(new)
            e, _w, _a = self.backend.apply(old, new)
            if e:
                return False, e
            aliases = data.get("aliases") or {}
            if isinstance(aliases, dict):
                self.store.replace_aliases(aliases)
                self.monitor.reload_aliases()
            totals = data.get("totals") or {}
            if isinstance(totals, dict):
                clean = {}
                for ip, v in totals.items():
                    try:
                        clean[ip] = (int(v[0]), int(v[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
                self.store.replace_totals(clean)
                self.monitor.set_totals(clean)
        return True, []

    # 请求上下文（由 httpd 通过 contextvars 注入）
    def _request_token(self):
        ctx = httpd_mod._req_ctx.get()
        return (ctx or {}).get("token", "")

    def _client_ip(self):
        ctx = httpd_mod._req_ctx.get()
        return (ctx or {}).get("ip", "unknown")
