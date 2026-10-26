# -*- coding: utf-8 -*-
"""命令行入口：run / demo / setup / check / reset-password / version。"""
import argparse
import getpass
import logging
import os
import platform
import sys

from . import APP_NAME, APP_NAME_EN, VERSION
from . import config as config_mod
from . import core
from .app import App


def _default_paths(demo=False):
    if demo or not platform.system().startswith("Linux"):
        base = os.path.abspath(os.path.join("data"))
        return (os.path.join(base, "config.json"), base,
                os.path.join(base, "easyrouter.log"))
    return ("/etc/easyrouter/config.json", "/var/lib/easyrouter",
            "/var/log/easyrouter/easyrouter.log")


def _setup_logging(logfile, verbose=False):
    handlers = [logging.StreamHandler()]
    if logfile:
        try:
            d = os.path.dirname(logfile)
            if d:
                os.makedirs(d, exist_ok=True)
            handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
        except OSError as e:
            sys.stderr.write("日志文件不可写（%s），仅输出到控制台\n" % e)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _banner(host, port, demo, password_hint=""):
    url_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    lines = [
        "",
        "=" * 46,
        "  %s %s 已启动" % (APP_NAME, APP_NAME_EN),
        "  版本: v%s" % VERSION,
        "  模式: %s" % ("演示模式（模拟数据）" if demo else "真实路由模式"),
        "  管理地址: http://%s:%d" % (url_host, port),
    ]
    if demo:
        lines.append("  演示模式登录: 用户名 admin，密码 admin123")
    if password_hint:
        lines.append("  " + password_hint)
    lines += ["  按 Ctrl+C 退出", "=" * 46, ""]
    print("\n".join(lines))


def cmd_run(args):
    demo = bool(args.demo)
    if demo is False and not platform.system().startswith("Linux"):
        print("提示：当前不是 Linux 系统，自动切换到演示模式。")
        demo = True
    conf, data, logf = _default_paths(demo)
    if args.config:
        conf = args.config
    if args.data:
        data = args.data
    if not logf:
        logf = os.path.join(data, "easyrouter.log")
    _setup_logging(logf, args.verbose)
    log = logging.getLogger("easyrouter")

    app = App(conf, data, log, demo=demo)
    if args.port or args.host:
        web = app.cfg.setdefault("web", {})
        if args.host:
            web["host"] = args.host
        if args.port:
            web["port"] = int(args.port)
        config_mod.save(conf, app.cfg)
    host, port = app.start()
    _banner(host, port, demo)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        app.stop()
    return 0


def cmd_demo(args):
    import types
    ns = types.SimpleNamespace(demo=True, config=None, data=None,
                               port=args.port, host=None, verbose=False)
    return cmd_run(ns)


def cmd_setup(args):
    if not platform.system().startswith("Linux"):
        print("交互式安装向导需要在 Linux（Debian/Ubuntu）上运行。")
        print("Windows/macOS 可运行：python3 -m easyrouter demo 预览界面。")
        return 1
    conf, _, _ = _default_paths()
    if args.config:
        conf = args.config
    if os.geteuid() != 0:
        print("请以 root 运行安装向导：sudo python3 -m easyrouter setup")
        return 1

    cfg, state = config_mod.load(conf)
    if cfg.get("setup_done"):
        print("已存在安装完成的配置：%s" % conf)
        ans = input("是否覆盖重新配置？(y/N) ").strip().lower()
        if ans != "y":
            return 0
        cfg = config_mod.new_default()

    backend = core.create_backend("linux", log=logging.getLogger("setup"))
    ifaces = [i for i in backend.interface_list() if not i.get("is_loopback")]
    if not ifaces:
        print("未检测到任何物理网卡！")
        return 1
    print("\n检测到以下网卡：")
    for idx, it in enumerate(ifaces):
        addrs = ", ".join(it.get("addrs") or ["无地址"])
        print("  [%d] %-10s MAC=%s 状态=%s 地址=%s"
              % (idx, it["name"], it.get("mac", ""), it.get("state"), addrs))
    lan_idx = _ask_int("请选择 LAN（内网）网卡编号", 0, len(ifaces) - 1, 0)
    wan_idx = _ask_int("请选择 WAN（外网）网卡编号（与 LAN 相同则跳过）",
                       0, len(ifaces) - 1, 1)
    lan_if = ifaces[lan_idx]["name"]
    wan_if = ifaces[wan_idx]["name"] if wan_idx != lan_idx else ""

    lan_ip = input("LAN 网关地址 [192.168.1.1]: ").strip() or "192.168.1.1"
    lan_mask = input("LAN 子网掩码 [255.255.255.0]: ").strip() or "255.255.255.0"
    gw = input("是否向 DHCP 客户端下发网关？(Y/n): ").strip().lower()
    send_gateway = gw != "n"

    wan_mode = "none"
    if wan_if:
        print("WAN 模式：0=不管理(系统已自行拨号) 1=DHCP自动获取 2=静态地址 3=PPPoE拨号")
        wan_mode = {"0": "none", "1": "dhcp", "2": "static", "3": "pppoe"}.get(
            input("请选择 [0]: ").strip() or "0", "none")

    while True:
        pw1 = getpass.getpass("设置管理员密码（至少 6 位）: ")
        if len(pw1) < 6:
            print("密码太短，请重新输入。")
            continue
        pw2 = getpass.getpass("再次输入密码: ")
        if pw1 != pw2:
            print("两次输入不一致，请重新输入。")
            continue
        break

    from . import auth as auth_mod
    net = config_mod.lan_network(
        {"network": {"lan": {"ip": lan_ip, "netmask": lan_mask}}})
    base = str(net.network_address).split(".")
    cfg.update({
        "setup_done": True,
        "admin": {"password_hash": auth_mod.hash_password(pw1), "username": "admin"},
        "network": {
            "wan": {"interface": wan_if, "mode": wan_mode},
            "lan": {"interface": lan_if, "ip": lan_ip, "netmask": lan_mask},
        },
        "dhcp": {
            "start": "%s.%s.%s.100" % (base[0], base[1], base[2]),
            "end": "%s.%s.%s.199" % (base[0], base[1], base[2]),
            "send_gateway": send_gateway,
        },
    })
    errors, warnings = config_mod.validate(cfg)
    if errors:
        print("\n配置有误：")
        for e in errors:
            print("  ✗ " + e)
        return 1
    config_mod.save(conf, cfg)

    print("\n正在应用网络配置…")
    e, w, applied = backend.apply(config_mod.new_default(), cfg)
    for x in applied:
        print("  ✓ " + x)
    for x in e:
        print("  ✗ " + x)
    for x in warnings + w:
        print("  ! " + x)

    print("\n安装完成！")
    print("  启动服务: systemctl start easyrouter    （或 python3 -m easyrouter run）")
    print("  管理页面: http://%s" % lan_ip)
    if send_gateway is False:
        print("  提示：已配置 DHCP 不下发网关，客户端“默认网关”一栏将为空。")
    return 0


def _ask_int(prompt, lo, hi, default):
    while True:
        try:
            raw = input("%s [%d]: " % (prompt, default)).strip()
            if raw == "":
                return default
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print("输入无效，请输入 %d-%d 之间的数字。" % (lo, hi))


def cmd_check(args):
    ok = True
    lines = []
    lines.append("== %s 环境自检 ==" % APP_NAME)
    sysname = platform.system()
    lines.append("操作系统: %s" % sysname)
    if sysname != "Linux":
        lines.append("✗ 需要 Linux（Debian 11+/Ubuntu 20.04+）")
        ok = False
    else:
        lines.append("✓ 操作系统: Linux")
        lines.append("✓ 以 root 运行" if os.geteuid() == 0 else "✗ 请以 root 运行")

        from .core import linux_util
        for tool, pkg in (("nft", "nftables"), ("dnsmasq", "dnsmasq-base"),
                          ("ip", "iproute2"), ("dhclient", "isc-dhcp-client"),
                          ("pppd", "ppp"), ("conntrack", "conntrack")):
            rc, _, _ = linux_util.run(["which", tool], timeout=10)
            lines.append("%s %s" % ("✓" if rc == 0 else "✗", "%s（apt install %s）" % (tool, pkg)))
            if rc != 0:
                ok = False
        fwd = linux_util.sysctl_get("net.ipv4.ip_forward")
        lines.append("IP 转发: %s" % ("✓ 已开启" if fwd == "1" else "✗ 未开启（%s）" % fwd))
        acct = linux_util.sysctl_get("net.netfilter.nf_conntrack_acct")
        lines.append("连接跟踪计费: %s" % ("✓ 已开启" if acct == "1" else "✗ 未开启（%s）" % acct))
        from .core import linux_conntrack
        lines.append("出口会话总数(conntrack): %s" % linux_conntrack.read_count())
        conf, _, _ = _default_paths()
        lines.append("配置文件: %s（%s）" % (conf,
                      "已存在" if os.path.exists(conf) else "不存在，首次启动将进入安装向导"))
    print("\n".join(lines))
    return 0 if ok else 1


def cmd_reset_password(args):
    conf, _, _ = _default_paths()
    if args.config:
        conf = args.config
    cfg, state = config_mod.load(conf)
    if not cfg.get("setup_done"):
        print("系统尚未安装，无需重置密码。")
        return 1
    while True:
        pw1 = getpass.getpass("新密码（至少 6 位）: ")
        if len(pw1) < 6:
            print("密码太短。")
            continue
        pw2 = getpass.getpass("再次输入: ")
        if pw1 != pw2:
            print("两次输入不一致。")
            continue
        break
    from . import auth as auth_mod
    cfg["admin"]["password_hash"] = auth_mod.hash_password(pw1)
    config_mod.save(conf, cfg)
    print("管理员密码已重置。")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="easyrouter", description="%s %s —— 全中文软路由系统" % (APP_NAME, APP_NAME_EN))
    sub = parser.add_subparsers(dest="cmd")
    p_run = sub.add_parser("run", help="前台运行路由服务")
    p_run.add_argument("--config", help="配置文件路径")
    p_run.add_argument("--data", help="数据目录路径")
    p_run.add_argument("--port", type=int, help="覆盖管理端口")
    p_run.add_argument("--host", help="覆盖监听地址")
    p_run.add_argument("--demo", action="store_true", help="强制演示模式")
    p_run.add_argument("--verbose", action="store_true", help="调试日志")
    p_demo = sub.add_parser("demo", help="演示模式（模拟数据，无需真实网卡）")
    p_demo.add_argument("--port", type=int, default=8080)
    p_setup = sub.add_parser("setup", help="交互式安装向导（Linux）")
    p_setup.add_argument("--config", help="配置文件路径")
    p_check = sub.add_parser("check", help="运行环境自检（Linux）")
    p_rp = sub.add_parser("reset-password", help="重置管理员密码")
    p_rp.add_argument("--config", help="配置文件路径")
    sub.add_parser("version", help="显示版本信息")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "demo":
        return cmd_demo(args)
    if args.cmd == "setup":
        return cmd_setup(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "reset-password":
        return cmd_reset_password(args)
    if args.cmd == "version":
        print("%s %s v%s" % (APP_NAME, APP_NAME_EN, VERSION))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
