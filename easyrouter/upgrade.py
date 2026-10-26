# -*- coding: utf-8 -*-
"""应用升级：上传 ZIP（easyrouter/ + VERSION）、校验、备份、替换、重启与失败回滚。

只升级易路由应用，不涉及 Debian 系统镜像。
"""
import base64
import io
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import PurePosixPath

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "easyrouter")
MAX_ZIP = 12 * 1024 * 1024
MAX_UNPACKED = 40 * 1024 * 1024
VER_RE = re.compile(r"^[0-9A-Za-z._-]{1,32}$")


class UpgradeError(Exception):
    pass


def current_version():
    for p in (os.path.join(ROOT, "VERSION"),
              os.path.join(PKG, "__init__.py")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                text = f.read()
            if p.endswith("VERSION"):
                return text.strip() or "unknown"
            m = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
            if m:
                return m.group(1)
        except OSError:
            continue
    return "unknown"


def _read_version(zf):
    names = zf.namelist()
    if "VERSION" not in names or "easyrouter/__init__.py" not in names:
        raise UpgradeError("升级包结构不正确：需要包含 easyrouter/ 目录和 VERSION 文件")
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in PurePosixPath(name).parts:
            raise UpgradeError("升级包包含非法路径：%s" % name)
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise UpgradeError("升级包不能包含符号链接")
        total += info.file_size
        if total > MAX_UNPACKED:
            raise UpgradeError("升级包解压后体积过大")
    try:
        version = zf.read("VERSION").decode("utf-8", "replace").strip()
    except Exception:
        raise UpgradeError("无法读取升级包版本号")
    if not version or not VER_RE.match(version):
        raise UpgradeError("升级包版本号无效")
    return version


def validate_zip(data):
    if not data:
        raise UpgradeError("没有收到升级包")
    if len(data) > MAX_ZIP:
        raise UpgradeError("升级包不能超过 12MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UpgradeError("不是有效的 ZIP 升级包")
    with zf:
        return _read_version(zf)


def _backup_dir(app):
    d = os.path.join(app.data_dir, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _prune_backups(app, keep=5):
    d = _backup_dir(app)
    items = sorted(
        [os.path.join(d, x) for x in os.listdir(d) if x.startswith("app-")],
        key=lambda p: os.path.getmtime(p), reverse=True)
    for p in items[keep:]:
        shutil.rmtree(p, ignore_errors=True)


def status(app):
    backups = []
    d = _backup_dir(app)
    try:
        for name in sorted(os.listdir(d), reverse=True):
            if name.startswith("app-"):
                p = os.path.join(d, name)
                backups.append({"name": name,
                                "created": int(os.path.getmtime(p))})
    except OSError:
        pass
    supported = (not app.demo) and bool(shutil.which("systemctl")) and \
        os.path.isdir("/run/systemd/system") and hasattr(os, "geteuid") and os.geteuid() == 0
    return {
        "current_version": current_version(),
        "supported": supported,
        "demo": app.demo,
        "backups": backups[:10],
        "max_mb": MAX_ZIP // (1024 * 1024),
    }


def _write_helper(app, backup_path, old_path, version):
    port = int(app.cfg.get("web", {}).get("port") or 80)
    log = os.path.join(app.data_dir, "upgrade.log")
    script = os.path.join(app.data_dir, "upgrade-%d.sh" % int(time.time()))
    health = "http://127.0.0.1:%d/api/health" % port
    content = """#!/bin/bash
exec >>{log} 2>&1
echo "=== upgrade {version} at $(date) ==="
sleep 1
systemctl restart easyrouter
sleep 8
if /usr/bin/python3 -c "import urllib.request; urllib.request.urlopen('{health}', timeout=3)" >/dev/null 2>&1; then
  rm -rf {old}
  echo "upgrade ok"
  exit 0
fi
echo "health check failed, rolling back"
rm -rf {pkg}
mv {backup} {pkg}
systemctl restart easyrouter
exit 1
""".format(log=shlex.quote(log), version=version,
           health=health, old=shlex.quote(old_path),
           pkg=shlex.quote(PKG), backup=shlex.quote(backup_path))
    with open(script, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(script, 0o700)
    return script


def install(app, zip_bytes):
    """安装升级包。返回 (ok, message, version)。"""
    version = validate_zip(zip_bytes)
    if app.demo:
        return True, "演示模式：升级包校验通过（未实际替换程序）", version
    if not status(app)["supported"]:
        raise UpgradeError("当前环境不支持自动升级（需要 root + systemd）")
    tmp = tempfile.mkdtemp(prefix="er-upgrade-", dir=app.data_dir)
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp)
        src = os.path.join(tmp, "easyrouter")
        if not os.path.isfile(os.path.join(src, "__init__.py")):
            raise UpgradeError("升级包缺少 easyrouter/__init__.py")
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_path = os.path.join(_backup_dir(app),
                                   "app-%s-%s" % (current_version(), ts))
        shutil.copytree(PKG, backup_path,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        stage = os.path.join(ROOT, ".easyrouter-upgrade-%s" % ts)
        if os.path.exists(stage):
            shutil.rmtree(stage, ignore_errors=True)
        shutil.copytree(src, stage)
        old = os.path.join(ROOT, ".easyrouter-old-%s" % ts)
        os.rename(PKG, old)
        try:
            os.rename(stage, PKG)
        except Exception:
            os.rename(old, PKG)
            raise UpgradeError("替换程序目录失败，已恢复旧版本")
        script = _write_helper(app, backup_path, old, version)
        subprocess.Popen(["/bin/bash", script], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _prune_backups(app)
        app.log.info("应用升级已提交：%s -> %s，备份 %s", current_version(), version, backup_path)
        return True, "升级包已安装，服务将在数秒后重启；若健康检查失败会自动回滚", version
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restore_backup(app, name):
    """从列表中的备份恢复应用目录（供紧急回滚）。"""
    if app.demo:
        return False, "演示模式不支持回滚"
    safe = os.path.basename(name or "")
    if not safe.startswith("app-"):
        return False, "备份名称无效"
    src = os.path.join(_backup_dir(app), safe)
    if not os.path.isdir(src):
        return False, "备份不存在"
    ts = time.strftime("%Y%m%d-%H%M%S")
    stage = os.path.join(ROOT, ".easyrouter-restore-%s" % ts)
    shutil.copytree(src, stage)
    old = os.path.join(ROOT, ".easyrouter-restore-old-%s" % ts)
    os.rename(PKG, old)
    try:
        os.rename(stage, PKG)
    except Exception:
        os.rename(old, PKG)
        return False, "恢复失败，已保留当前版本"
    return True, "已恢复备份 %s，请重启服务生效" % safe
