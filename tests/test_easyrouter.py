# -*- coding: utf-8 -*-
"""易路由 EasyRouter 单元测试（无需 Linux 环境）。

运行: python -m unittest discover -s tests -v
"""
import ipaddress
import os
import shutil
import struct
import tempfile
import time
import unittest

from easyrouter import auth
from easyrouter import config as config_mod
from easyrouter import gateways as gw_mod
from easyrouter import store as store_mod
from easyrouter.core import demo as demo_mod
from easyrouter.core import linux_dnsmasq
from easyrouter.core import linux_nft
from easyrouter.core import nbns as nbns_mod
from easyrouter.monitor import ip_sort_key, _kind_of


def make_cfg(**over):
    cfg = config_mod.new_default()
    cfg["setup_done"] = True
    cfg["network"]["wan"]["interface"] = "eth0"
    cfg["network"]["lan"]["interface"] = "eth1"
    for k, v in over.items():
        cfg[k] = v
    return cfg


# 测试夹具放在工作区（tests 目录）内，避免受系统临时目录写限制影响
HERE = os.path.dirname(os.path.abspath(__file__))


def workspace_tempdir():
    import uuid
    d = os.path.join(HERE, ".t-" + uuid.uuid4().hex[:12])
    os.makedirs(d, exist_ok=False)
    return d


class TestConfig(unittest.TestCase):
    def test_defaults_valid(self):
        cfg = make_cfg()
        errors, _ = config_mod.validate(cfg)
        self.assertEqual(errors, [])

    def test_mac_norm(self):
        self.assertEqual(config_mod.mac_norm("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(config_mod.mac_norm("AA-BB-CC-DD-EE-FF"), "AA:BB:CC:DD:EE:FF")
        self.assertIsNone(config_mod.mac_norm("12:34"))
        self.assertIsNone(config_mod.mac_norm(""))

    def test_netmask(self):
        self.assertTrue(config_mod.is_netmask("255.255.255.0"))
        self.assertTrue(config_mod.is_netmask("255.255.0.0"))
        self.assertFalse(config_mod.is_netmask("255.0.255.0"))
        self.assertEqual(config_mod.mask_to_prefix("255.255.255.0"), 24)

    def test_dhcp_range_must_be_in_lan(self):
        cfg = make_cfg()
        cfg["dhcp"]["start"] = "10.0.0.100"   # 不在 192.168.1.0/24
        cfg["dhcp"]["end"] = "10.0.0.199"
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("地址池" in e for e in errors))

    def test_wan_and_lan_same_iface_rejected(self):
        cfg = make_cfg()
        cfg["network"]["lan"]["interface"] = "eth0"
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("同一块网卡" in e for e in errors))

    def test_lease_time_format(self):
        cfg = make_cfg()
        cfg["dhcp"]["lease_time"] = "3q"
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("租约时间" in e for e in errors))

    def test_custom_gateway_validation(self):
        cfg = make_cfg()
        cfg["dhcp"]["gateway"] = "not-an-ip"
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("网关地址无效" in e for e in errors))
        cfg["dhcp"]["gateway"] = "192.168.10.1"
        errors, _ = config_mod.validate(cfg)
        self.assertEqual(errors, [])

    def test_lease_seconds(self):
        self.assertEqual(config_mod.lease_seconds("12h"), 43200)
        self.assertEqual(config_mod.lease_seconds("7d"), 604800)
        self.assertEqual(config_mod.lease_seconds("3600s"), 3600)
        self.assertEqual(config_mod.lease_seconds("infinite"), 0)
        self.assertEqual(config_mod.lease_seconds("bogus"), 43200)

    def test_save_load_roundtrip(self):
        d = workspace_tempdir()
        try:
            path = os.path.join(d, "config.json")
            cfg = make_cfg()
            config_mod.save(path, cfg)
            loaded, state = config_mod.load(path)
            self.assertEqual(state, "ok")
            self.assertEqual(loaded["network"]["lan"]["ip"], cfg["network"]["lan"]["ip"])
            self.assertTrue(loaded["dhcp"]["send_gateway"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestDnsmasqConf(unittest.TestCase):
    """核心需求：DHCP 不下发网关时客户端网关一栏为空。"""

    def test_gateway_on(self):
        svc = linux_dnsmasq.DnsmasqService()
        svc.lease_path = "/var/lib/easyrouter/dnsmasq.leases"
        cfg = make_cfg()
        cfg["dhcp"]["send_gateway"] = True
        conf = svc.build_conf(cfg)
        self.assertIn("dhcp-option=option:router,192.168.1.1", conf)
        self.assertNotIn("dhcp-option=3\n", conf)

    def test_gateway_off_sends_no_router_option(self):
        svc = linux_dnsmasq.DnsmasqService()
        svc.lease_path = "/var/lib/easyrouter/dnsmasq.leases"
        cfg = make_cfg()
        cfg["dhcp"]["send_gateway"] = False
        conf = svc.build_conf(cfg)
        self.assertNotIn("option:router", conf)
        self.assertIn("dhcp-option=3", conf)   # dnsmasq 官方支持：不发送路由器选项
        self.assertIn("dhcp-range=192.168.1.100,192.168.1.199,255.255.255.0,12h", conf)

    def test_static_lease_and_dns_servers(self):
        svc = linux_dnsmasq.DnsmasqService()
        svc.lease_path = "/var/lib/easyrouter/dnsmasq.leases"
        cfg = make_cfg()
        cfg["dhcp"]["static_leases"] = [{"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.50", "name": "打印机"}]
        cfg["dhcp"]["dns_servers"] = ["223.5.5.5", "119.29.29.29"]
        conf = svc.build_conf(cfg)
        self.assertIn("dhcp-host=AA:BB:CC:DD:EE:FF,192.168.1.50,打印机,infinite", conf)
        self.assertIn("dhcp-option=option:dns-server,223.5.5.5", conf)
        self.assertIn("server=223.5.5.5", conf)

    def test_custom_dhcp_gateway(self):
        """软路由只做 DHCP 时，可把上游路由器地址作为客户端网关下发。"""
        svc = linux_dnsmasq.DnsmasqService()
        svc.lease_path = "/var/lib/easyrouter/dnsmasq.leases"
        cfg = make_cfg()
        cfg["dhcp"]["gateway"] = "192.168.10.1"
        conf = svc.build_conf(cfg)
        self.assertIn("dhcp-option=option:router,192.168.10.1", conf)
        self.assertNotIn("dhcp-option=option:router,192.168.1.1", conf)
        cfg["dhcp"]["send_gateway"] = False
        conf = svc.build_conf(cfg)
        self.assertIn("dhcp-option=3", conf)
        self.assertNotIn("option:router", conf)

    def test_multiple_pools_tagged_and_vlan(self):
        svc = linux_dnsmasq.DnsmasqService()
        svc.lease_path = "/var/lib/easyrouter/dnsmasq.leases"
        cfg = make_cfg()
        cfg["dhcp"]["pools"] = [
            {"id": "p-office", "name": "办公网", "type": "tagged", "enabled": True,
             "start": "192.168.1.150", "end": "192.168.1.199", "gateway": "192.168.10.1",
             "dns_servers": ["223.5.5.5"], "lease_time": "2h"},
            {"id": "p-guest", "name": "访客VLAN", "type": "vlan", "enabled": True,
             "vlan_id": 20, "parent": "eth1", "ip": "192.168.20.1",
             "netmask": "255.255.255.0", "start": "192.168.20.100",
             "end": "192.168.20.199", "lease_time": "1h"},
        ]
        cfg["dhcp"]["static_leases"] = [
            {"mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.160", "name": "PC1",
             "pool": "p-office"},
            {"mac": "AA:BB:CC:DD:EE:02", "ip": "192.168.20.110", "name": "PC2",
             "pool": "p-guest"},
        ]
        conf = svc.build_conf(cfg)
        self.assertIn("interface=eth1.20", conf)
        self.assertIn("listen-address=192.168.20.1", conf)
        self.assertIn("dhcp-range=set:p-office,192.168.1.150,192.168.1.199,255.255.255.0,2h", conf)
        self.assertIn("dhcp-range=set:p-guest,192.168.20.100,192.168.20.199,255.255.255.0,1h", conf)
        self.assertIn("dhcp-option=tag:p-office,3,192.168.10.1", conf)
        self.assertIn("dhcp-option=tag:p-guest,3,192.168.20.1", conf)
        self.assertIn("dhcp-option=tag:p-office,6,223.5.5.5", conf)
        self.assertIn("dhcp-host=AA:BB:CC:DD:EE:01,set:p-office,192.168.1.160,PC1,infinite", conf)
        self.assertIn("dhcp-host=AA:BB:CC:DD:EE:02,set:p-guest,192.168.20.110,PC2,infinite", conf)

    def test_pool_validation(self):
        cfg = make_cfg()
        cfg["dhcp"]["pools"] = [{"id": "p1", "name": "办公", "type": "tagged",
                                 "start": "10.0.0.10", "end": "10.0.0.20"}]
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("必须位于" in e for e in errors))
        cfg["dhcp"]["pools"] = [{"id": "p1", "name": "访客", "type": "vlan",
                                 "vlan_id": 20, "ip": "192.168.20.1",
                                 "netmask": "255.255.255.0",
                                 "start": "192.168.20.100", "end": "192.168.20.199"}]
        cfg["dhcp"]["static_leases"] = [{"mac": "AA:BB:CC:DD:EE:02",
                                         "ip": "192.168.20.110", "pool": "p1"}]
        errors, _ = config_mod.validate(cfg)
        self.assertEqual(errors, [])

    def test_pool_exclude_and_custom_options(self):
        svc = linux_dnsmasq.DnsmasqService()
        svc.lease_path = "/var/lib/easyrouter/dnsmasq.leases"
        cfg = make_cfg()
        cfg["dhcp"]["pools"] = [{
            "id": "p-office", "name": "办公网", "type": "tagged", "enabled": True,
            "start": "192.168.1.100", "end": "192.168.1.110",
            "exclude": "192.168.1.104-192.168.1.106",
            "extra_options": "43,01:04:C0:A8:0A:01\n66,192.168.1.5",
            "lease_time": "2h",
        }]
        conf = svc.build_conf(cfg)
        self.assertIn("dhcp-range=set:p-office,192.168.1.100,192.168.1.103,255.255.255.0,2h", conf)
        self.assertIn("dhcp-range=set:p-office,192.168.1.107,192.168.1.110,255.255.255.0,2h", conf)
        self.assertNotIn("dhcp-range=set:p-office,192.168.1.100,192.168.1.110", conf)
        self.assertIn("dhcp-option=tag:p-office,43,01:04:C0:A8:0A:01", conf)
        self.assertIn("dhcp-option=tag:p-office,66,192.168.1.5", conf)

    def test_pool_bad_exclude_validation(self):
        cfg = make_cfg()
        cfg["dhcp"]["pools"] = [{
            "id": "p1", "name": "办公", "type": "tagged",
            "start": "192.168.1.100", "end": "192.168.1.110",
            "exclude": "192.168.2.5",
        }]
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("排除地址" in e for e in errors))


class TestNft(unittest.TestCase):
    def test_base_ruleset(self):
        svc = linux_nft.NftService()
        cfg = make_cfg()
        rs = svc.base_ruleset(cfg)
        self.assertIn('table inet easyrouter', rs)
        self.assertIn('chain acct', rs)
        self.assertIn('masquerade', rs)
        self.assertIn('"eth1"', rs)

    def test_rule_args_tx(self):
        svc = linux_nft.NftService()
        cfg = make_cfg()
        args = svc._rule_args(cfg, "192.168.1.10", "tx")
        self.assertIsNotNone(args)
        joined = " ".join(args)
        self.assertIn("iifname eth1", joined)
        self.assertIn("ip saddr 192.168.1.10", joined)
        self.assertIn("dev:192.168.1.10:tx", joined)

    def test_bad_ip_rejected(self):
        svc = linux_nft.NftService()
        cfg = make_cfg()
        self.assertIsNone(svc._rule_args(cfg, "1.2.3.4; rm -rf /", "rx"))


class TestAuth(unittest.TestCase):
    def test_hash_verify(self):
        h = auth.hash_password("secret123")
        self.assertTrue(h.startswith("pbkdf2_sha256$"))
        self.assertTrue(auth.verify_password("secret123", h))
        self.assertFalse(auth.verify_password("wrong", h))
        self.assertFalse(auth.verify_password("", h))

    def test_session(self):
        sm = auth.SessionManager(ttl=1)
        t = sm.create()
        self.assertTrue(sm.valid(t))
        sm.destroy(t)
        self.assertFalse(sm.valid(t))

    def test_login_limiter(self):
        lm = auth.LoginLimiter()
        for _ in range(5):
            lm.fail("1.2.3.4")
        ok, wait = lm.check("1.2.3.4")
        self.assertFalse(ok)
        self.assertGreater(wait, 0)
        self.assertTrue(lm.check("5.6.7.8")[0])


class TestStore(unittest.TestCase):
    def test_alias_and_totals(self):
        d = workspace_tempdir()
        try:
            st = store_mod.Store(os.path.join(d, "t.db"))
            st.set_alias("aa:bb:cc:dd:ee:ff", "客厅电视")
            self.assertEqual(st.get_aliases()["AA:BB:CC:DD:EE:FF"], "客厅电视")
            st.set_alias("AA:BB:CC:DD:EE:FF", "")   # 清空即删除
            self.assertNotIn("AA:BB:CC:DD:EE:FF", st.get_aliases())
            st.save_totals({"192.168.1.5": (100, 200)})
            self.assertEqual(st.get_totals()["192.168.1.5"], (100, 200))
            st.close()
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestDemoBackend(unittest.TestCase):
    def test_simulation(self):
        b = demo_mod.DemoBackend()
        b.start(config_mod.new_default(), None)
        for _ in range(5):
            b.step(2.0)
        ifaces = b.interfaces()
        self.assertIn("wan0", ifaces)
        ct = b.conntrack()
        self.assertGreater(ct["total"], 0)
        self.assertLessEqual(ct["tcp"] + ct["udp"] + ct["icmp"] + ct["other"], ct["total"] + 4)
        devs = b.leases()
        self.assertGreaterEqual(len(devs), 15)
        self.assertTrue(all(devs[i]["ip"] < devs[i + 1]["ip"] for i in range(len(devs) - 1)),
                        "演示租约应按 IP 顺序排列")

    def test_nbns_sim(self):
        b = demo_mod.DemoBackend()
        self.assertEqual(b.nbns_name("192.168.1.100"), "小米 14 Pro")
        self.assertIsNone(b.nbns_name("10.9.9.9"))


class TestNbns(unittest.TestCase):
    def test_parse_response(self):
        # 构造一个 NBNS 应答：一个名字 "MYPC"
        def enc(name):
            out = bytearray()
            for ch in name.ljust(15, " ")[:15].upper():
                x = ord(ch)
                out.append(ord("A") + (x >> 4))
                out.append(ord("A") + (x & 0x0F))
            return bytes(out)

        qname = b"\x20" + enc("*") + b"\x00"
        header = struct.pack(">HHHHHH", 0x1234, 0x8500, 1, 1, 0, 0)
        question = qname + struct.pack(">HH", 0x0020, 0x0001)
        rdata = bytes([1]) + "MYPC".ljust(15, " ").encode() + bytes([0x00]) + struct.pack(">H", 0x0000)
        answer = (b"\xc0\x0c" + struct.pack(">HHIH", 0x0020, 0x0001, 300, len(rdata)) + rdata)
        name = nbns_mod.parse_response(header + question + answer)
        self.assertEqual(name, "MYPC")

    def test_parse_garbage(self):
        self.assertIsNone(nbns_mod.parse_response(b"junk"))
        self.assertIsNone(nbns_mod.parse_response(b""))


class TestMonitorHelpers(unittest.TestCase):
    def test_ip_sort_natural(self):
        ips = ["192.168.1.100", "192.168.1.2", "192.168.1.10", "192.168.1.1"]
        ips.sort(key=ip_sort_key)
        self.assertEqual(ips, ["192.168.1.1", "192.168.1.2", "192.168.1.10", "192.168.1.100"])

    def test_kind_detect(self):
        self.assertEqual(_kind_of("小米", "Redmi K70", ""), "phone")
        self.assertEqual(_kind_of("Apple", "iPhone 15", ""), "phone")
        self.assertEqual(_kind_of("Apple", "MacBook Pro", ""), "computer")
        self.assertEqual(_kind_of("群晖", "NAS", ""), "nas")
        self.assertEqual(_kind_of("海康威视", "门口摄像头", ""), "camera")
        self.assertEqual(_kind_of("", "未知设备", ""), "device")


class TestRouter(unittest.TestCase):
    def test_route_match(self):
        from easyrouter import httpd as httpd_mod
        r = httpd_mod.Router()
        r.add("GET", r"/api/devices", lambda *a: None)
        m = r.match("GET", "/api/devices")
        self.assertIsNotNone(m)
        self.assertIsNone(r.match("POST", "/api/devices"))
        self.assertIsNone(r.match("GET", "/api/devices/"))


class TestGateways(unittest.TestCase):
    def test_oid_roundtrip(self):
        tlv = gw_mod._ber_oid("1.3.6.1.2.1.1.1.0")
        tag, content, _ = gw_mod._read_tlv(tlv, 0)
        self.assertEqual(tag, 0x06)
        self.assertEqual(gw_mod._decode_value(0x06, content), "1.3.6.1.2.1.1.1.0")

    def test_parse_snmp_response(self):
        oid = gw_mod._ber_oid("1.3.6.1.2.1.1.1.0")
        value = gw_mod._tlv(0x41, (12345).to_bytes(2, "big"))
        varbind = gw_mod._tlv(0x30, oid + value)
        pdu = gw_mod._tlv(0xA2, gw_mod._ber_int(7) + gw_mod._ber_int(0) +
                          gw_mod._ber_int(0) + gw_mod._tlv(0x30, varbind))
        packet = gw_mod._tlv(0x30, gw_mod._ber_int(1) +
                             gw_mod._ber_octets("public") + pdu)
        out = gw_mod._parse_snmp_message(packet)
        self.assertEqual(out["value"], 12345)
        self.assertEqual(out["error_status"], 0)

    def test_demo_probe(self):
        r = gw_mod.probe_gateway({"id": "gw-test", "name": "测试", "ip": "10.0.0.1",
                                  "method": "demo"})
        self.assertIn("ok", r)
        self.assertIn("sessions", r)
        self.assertIn("hosts", r)

    def test_gateway_config_validation(self):
        cfg = make_cfg()
        cfg["gateways"] = [{"id": "g1", "name": "电信", "ip": "192.168.10.1",
                            "method": "snmp"}]
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("OID" in e for e in errors))
        cfg["gateways"][0]["sessions_oid"] = "1.3.6.1.2.1.1.1.0"
        errors, _ = config_mod.validate(cfg)
        self.assertEqual(errors, [])

    def test_gateway_bad_ip(self):
        cfg = make_cfg()
        cfg["gateways"] = [{"id": "g1", "name": "电信", "ip": "999.1.1.1",
                            "method": "auto"}]
        errors, _ = config_mod.validate(cfg)
        self.assertTrue(any("IP 地址无效" in e for e in errors))


class TestUpgradePackage(unittest.TestCase):
    @staticmethod
    def _zip(files):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, content in files.items():
                z.writestr(name, content)
        return buf.getvalue()

    def test_valid(self):
        from easyrouter import upgrade
        data = self._zip({"VERSION": "1.1.0\n",
                          "easyrouter/__init__.py": "VERSION='1.1.0'\n"})
        self.assertEqual(upgrade.validate_zip(data), "1.1.0")

    def test_missing_version(self):
        from easyrouter import upgrade
        data = self._zip({"easyrouter/__init__.py": "x=1\n"})
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.validate_zip(data)

    def test_path_traversal(self):
        from easyrouter import upgrade
        data = self._zip({"VERSION": "1.1.0",
                          "easyrouter/__init__.py": "x=1\n",
                          "../evil.txt": "x"})
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.validate_zip(data)

    def test_bad_zip(self):
        from easyrouter import upgrade
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.validate_zip(b"not a zip")


if __name__ == "__main__":
    unittest.main()
