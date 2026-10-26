# -*- coding: utf-8 -*-
"""采集后端。"""
from .base import BackendBase
from .demo import DemoBackend


def create_backend(kind, log=None, **kw):
    """按名称创建后端。linux 在非 Linux 平台上可能无法使用。"""
    if kind == "demo":
        return DemoBackend()
    if kind == "linux":
        from .linux import LinuxBackend
        return LinuxBackend(log=log, **kw)
    raise ValueError("未知后端类型: %s" % kind)


def auto_backend(log=None):
    """按平台自动选择后端。"""
    import platform
    if platform.system() == "Linux":
        return create_backend("linux", log=log)
    return create_backend("demo", log=log)
