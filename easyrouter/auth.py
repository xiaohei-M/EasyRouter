# -*- coding: utf-8 -*-
"""登录认证：PBKDF2 密码哈希、会话令牌、登录失败限流。"""
import base64
import hashlib
import hmac
import secrets
import threading
import time

ITERATIONS = 120000
SESSION_TTL = 7 * 86400  # 会话有效期 7 天


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(password, stored):
    if not stored or not password:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


class SessionManager:
    def __init__(self, ttl=SESSION_TTL):
        self.ttl = ttl
        self._sessions = {}
        self._lock = threading.Lock()

    def create(self):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._sessions[token] = time.time() + self.ttl
        return token

    def valid(self, token):
        if not token:
            return False
        with self._lock:
            exp = self._sessions.get(token)
            if exp is None:
                return False
            if time.time() > exp:
                self._sessions.pop(token, None)
                return False
            return True

    def destroy(self, token):
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def _prune_locked(self):
        now = time.time()
        for t in [t for t, exp in self._sessions.items() if now > exp]:
            self._sessions.pop(t, None)


class LoginLimiter:
    """同一 IP 登录失败限流：5 次失败锁 60 秒，之后每再失败一次翻倍。"""

    def __init__(self):
        self._data = {}  # ip -> [fails, first_ts, blocked_until]
        self._lock = threading.Lock()

    def check(self, ip):
        """返回 (True, None) 或 (False, 等待秒数)。"""
        with self._lock:
            d = self._data.get(ip)
            if not d:
                return True, None
            fails, first, blocked = d
            if time.time() < blocked:
                return False, int(blocked - time.time()) + 1
            if fails >= 5 and time.time() - first > 3600:
                self._data.pop(ip, None)
            return True, None

    def fail(self, ip):
        with self._lock:
            d = self._data.get(ip)
            now = time.time()
            if not d:
                self._data[ip] = [1, now, 0]
                return 0
            d[0] += 1
            if d[0] >= 5:
                d[2] = now + min(60 * 2 ** (d[0] - 5), 3600)
            return max(0, int(d[2] - now))

    def ok(self, ip):
        with self._lock:
            self._data.pop(ip, None)
