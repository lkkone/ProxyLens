"""ProxyLens HTTP API. Standard library only; SQLite is the durable source of truth."""

import hashlib
import hmac
import json
import logging
import math
import mimetypes
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DATA = Path(os.environ.get("DATA_DIR", "/data"))
WEB = Path(__file__).parent / "web"
DOWNLOADS = Path(os.environ.get("DOWNLOAD_DIR", "/app/downloads"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))
DB_LOCK = threading.Lock()
LOGIN_LOCK = threading.Lock()
LOGIN_FAILURES = {}
logger = logging.getLogger("proxylens")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()


@contextmanager
def connect():
    db = sqlite3.connect(DATA / "proxylens.db", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, group_name TEXT NOT NULL,
          allow_offline INTEGER NOT NULL, token_hash TEXT NOT NULL UNIQUE,
          policy TEXT NOT NULL, created REAL NOT NULL, last_seen REAL, latest TEXT);
        CREATE TABLE IF NOT EXISTS reports(
          id INTEGER PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          at REAL NOT NULL, state TEXT NOT NULL, delay REAL);
        CREATE INDEX IF NOT EXISTS reports_device_time ON reports(device_id, at);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          at REAL NOT NULL, message TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_device_time ON events(device_id, at);
        """)
        if "notes" not in {r["name"] for r in db.execute("PRAGMA table_info(devices)")}:
            db.execute("ALTER TABLE devices ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if not ADMIN_USERNAME.strip() or len(ADMIN_PASSWORD) < 8:
            raise ValueError(
                "请通过 ADMIN_USERNAME 和 ADMIN_PASSWORD 配置账号与至少 8 位密码"
            )
        account = db.execute(
            "SELECT value FROM settings WHERE key='username'"
        ).fetchone()
        stored = db.execute(
            "SELECT value FROM settings WHERE key='password'"
        ).fetchone()
        password = json.loads(stored["value"]) if stored else None
        unchanged = (
            account
            and account["value"] == ADMIN_USERNAME
            and password
            and hmac.compare_digest(
                password_hash(ADMIN_PASSWORD, password["salt"]), password["hash"]
            )
        )
        if not unchanged:
            salt = secrets.token_hex(16)
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                (
                    "password",
                    json.dumps(
                        {"salt": salt, "hash": password_hash(ADMIN_PASSWORD, salt)}
                    ),
                ),
            )
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                ("username", ADMIN_USERNAME),
            )
            db.execute("DELETE FROM sessions")


def text(value, limit=200):
    if not isinstance(value, str):
        raise TypeError("文本字段格式错误")
    return value[:limit]


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"整数范围应为 {low}–{high}")
    return value


def number(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("数值格式错误")
    return value


def policy_from(body):
    green = integer(body.get("green_delay_ms", 300), 1, 9999)
    red = integer(body.get("red_delay_ms", 1000), 2, 10000)
    if red <= green:
        raise ValueError("红色延迟阈值必须大于绿色阈值")
    return {
        "green_delay_ms": green,
        "red_delay_ms": red,
        "report_interval": integer(body.get("report_interval", 30), 15, 300),
        "probe_interval": integer(body.get("probe_interval", 300), 60, 86400),
        "probe_enabled": body.get("probe_enabled", True) is True,
        "primary_group": "",
        "airport_label": "",
        "probe_url": "https://www.gstatic.com/generate_204",
    }


def clean_report(body):
    """Allowlist telemetry: no configs, subscription URLs, controller secrets or node credentials."""
    if body.get("schema_version") != 1 or body.get("adapter") != "mihomo":
        raise ValueError("不支持的上报协议或适配器")
    result = {
        k: text(body.get(k, ""), 200)
        for k in (
            "adapter",
            "hostname",
            "os",
            "arch",
            "agent_version",
            "core_version",
            "mode",
            "primary_group",
            "selected_node",
            "airport",
            "core_error",
            "system_proxy",
        )
    }
    result.update(
        schema_version=1,
        core_reachable=body.get("core_reachable") is True,
        tun_enabled=body.get("tun_enabled") is True,
    )
    probe = body.get("probe")
    if probe is not None:
        if not isinstance(probe, dict):
            raise ValueError("探测数据格式错误")
        result["probe"] = {
            "ok": probe.get("ok") is True,
            "delay_ms": number(probe.get("delay_ms")),
            "at": number(probe.get("at")),
            "node": text(probe.get("node", "")),
            "error": text(probe.get("error", "")),
            "target": text(probe.get("target", "")),
        }
    else:
        result["probe"] = None
    result["groups"] = []
    for g in body.get("groups", [])[:200]:
        result["groups"].append(
            {k: text(g.get(k, "")) for k in ("name", "type", "selected", "leaf")}
        )
    result["providers"] = []
    for p in body.get("providers", [])[:100]:
        item = {k: text(p.get(k, "")) for k in ("name", "type", "updated_at")}
        item["node_count"] = integer(p.get("node_count", 0), 0, 100000)
        item["usage"] = {
            k: number((p.get("usage") or {}).get(k))
            for k in ("upload", "download", "total", "expire")
        }
        result["providers"].append(item)
    result["nodes"] = []
    for n in body.get("nodes", [])[:2000]:
        result["nodes"].append(
            {
                "name": text(n.get("name", "")),
                "type": text(n.get("type", "")),
                "delay_ms": number(n.get("delay_ms")),
                "delay_at": text(n.get("delay_at", "")),
            }
        )
    return result


def telemetry_state(report, policy, now):
    if not report.get("core_reachable"):
        return "error"
    if report.get("mode") == "direct" or report.get("selected_node") in (
        "DIRECT",
        "REJECT",
        "REJECT-DROP",
    ):
        return "direct"
    probe = report.get("probe")
    if not policy["probe_enabled"] or not probe:
        return "unknown"
    age = now - (probe.get("at") or 0)
    if (
        probe.get("node") != report.get("selected_node")
        or age < -10
        or age > policy["probe_interval"] * 2 + 30
    ):
        return "unknown"
    if not probe["ok"]:
        return "error"
    delay = probe.get("delay_ms")
    if delay is None:
        return "unknown"
    if delay > policy.get("red_delay_ms", 1000):
        return "degraded"
    if delay > policy.get("green_delay_ms", 300):
        return "slow"
    return "healthy"


def serialize_device(db, row, now):
    p = json.loads(row["policy"])
    latest = json.loads(row["latest"]) if row["latest"] else None
    stale = row["last_seen"] is not None and now - row["last_seen"] > max(
        90, p["report_interval"] * 3
    )
    state = (
        "pending"
        if latest is None
        else ("offline" if stale else telemetry_state(latest, p, now))
    )
    # Fixed 5-minute slots; gaps are unknown/offline, never fabricated green beats.
    slot = 300
    end = int(now // slot) * slot
    start = end - 59 * slot
    bins = {}
    for r in db.execute(
        "SELECT at,state,delay FROM reports WHERE device_id=? AND at>=? ORDER BY at",
        (row["id"], start),
    ):
        key = int(r["at"] // slot) * slot
        bins[key] = {
            "at": key,
            "sample_at": r["at"],
            "state": r["state"],
            "delay_ms": r["delay"],
        }
    history = [
        bins.get(
            start + i * slot,
            {"at": start + i * slot, "sample_at": None, "state": "offline", "delay_ms": None},
        )
        for i in range(60)
    ]
    counts = db.execute(
        "SELECT SUM(state IN ('healthy','slow','degraded')) healthy, SUM(state IN ('healthy','slow','degraded','error')) tested FROM reports WHERE device_id=? AND at>=?",
        (row["id"], now - 86400),
    ).fetchone()
    events = [
        dict(e)
        for e in db.execute(
            "SELECT at,message FROM events WHERE device_id=? ORDER BY at DESC LIMIT 20",
            (row["id"],),
        )
    ]
    return {
        "id": row["id"],
        "notes": row["notes"],
        "name": row["name"],
        "group": row["group_name"],
        "allow_offline": bool(row["allow_offline"]),
        "last_seen": row["last_seen"],
        "state": state,
        "policy": p,
        "latest": latest,
        "history": history,
        "availability": round(counts["healthy"] / counts["tested"] * 100, 2)
        if counts["tested"]
        else None,
        "events": events,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Don't log bodies, authentication headers, query strings or credentials.
        logger.info(
            "%s %s %s",
            self.command,
            urlsplit(self.path).path,
            args[1] if len(args) > 1 else "",
        )

    def response(
        self, status, body, content_type="application/json; charset=utf-8", headers=None
    ):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("无效请求长度")
        if not 0 < size <= 1024 * 1024:
            raise ValueError("请求大小应在 1MB 以内")
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise TypeError("请求必须为 JSON 对象")
        return data

    def session(self, db):
        cookies = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
        token = cookies.get("proxylens_session", "")
        return (
            db.execute(
                "SELECT 1 FROM sessions WHERE hash=? AND expires>?",
                (digest(token), time.time()),
            ).fetchone()
            is not None
        )

    def cookie(self, token, max_age=604800):
        return (
            f"proxylens_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}"
            + ("; Secure" if COOKIE_SECURE else "")
        )

    def login_session(self, db):
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        db.execute(
            "INSERT INTO sessions VALUES(?,?)", (digest(token), time.time() + 604800)
        )
        return {"Set-Cookie": self.cookie(token)}

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        try:
            self.connection.settimeout(15)
            self.route(method)
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            json.JSONDecodeError,
        ) as exc:
            self.response(400, {"error": str(exc)[:200]})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            logger.exception("Request failed")
            self.response(500, {"error": "服务端错误，请查看容器日志"})

    def route(self, method):
        path = urlsplit(self.path).path
        if path == "/healthz" and method == "GET":
            with connect() as db:
                db.execute("SELECT 1").fetchone()
            return self.response(200, {"status": "ok", "version": "0.1.0"})
        if (
            not path.startswith("/api/")
            and not path.startswith("/downloads/")
            and method == "GET"
        ):
            assets = {
                "/": "index.html",
                "/admin": "index.html",
                "/admin/": "index.html",
            }
            relative_path = assets.get(path, path.lstrip("/"))
            file = (WEB / relative_path).resolve()
            if not file.is_relative_to(WEB.resolve()):
                return self.response(404, {"error": "页面不存在"})
            if file.is_file():
                return self.response(
                    200,
                    file.read_bytes(),
                    mimetypes.guess_type(str(file))[0] or "application/octet-stream",
                )
            return self.response(404, {"error": "页面不存在"})
        # SQLite mutation serialized to make setup/token rotation/report acceptance atomic.
        with DB_LOCK, connect() as db:
            if path == "/api/status" and method == "GET":
                now = time.time()
                devices = [
                    serialize_device(db, row, now)
                    for row in db.execute(
                        "SELECT * FROM devices ORDER BY group_name,created"
                    )
                ]
                for device in devices:
                    device.pop("events", None)
                    device.pop("notes", None)
                return self.response(
                    200, {"devices": devices, "server_time": now, "version": "0.1.0"}
                )
            if path == "/api/auth" and method == "GET":
                return self.response(200, {"authenticated": self.session(db)})
            if method in ("POST", "PATCH", "DELETE") and path != "/api/v1/report":
                if self.headers.get("X-ProxyLens-Request") != "1":
                    return self.response(403, {"error": "请求验证失败"})
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    return self.response(403, {"error": "来源验证失败"})
            if path == "/api/login" and method == "POST":
                ip = self.client_address[0]
                now = time.time()
                with LOGIN_LOCK:
                    failures = [t for t in LOGIN_FAILURES.get(ip, []) if t > now - 300]
                    if len(failures) >= 10:
                        return self.response(
                            429, {"error": "尝试过于频繁，请 5 分钟后再试"}
                        )
                body = self.body()
                password = text(body.get("password", ""), 1024)
                username = text(body.get("username", ""), 200)
                stored = db.execute(
                    "SELECT value FROM settings WHERE key='password'"
                ).fetchone()
                p = json.loads(stored["value"]) if stored else None
                account = db.execute(
                    "SELECT value FROM settings WHERE key='username'"
                ).fetchone()
                if (
                    not p
                    or not account
                    or not hmac.compare_digest(
                        username.encode(), account["value"].encode()
                    )
                    or not hmac.compare_digest(
                        password_hash(password, p["salt"]), p["hash"]
                    )
                ):
                    with LOGIN_LOCK:
                        LOGIN_FAILURES[ip] = failures + [now]
                    return self.response(401, {"error": "账号或密码错误"})
                with LOGIN_LOCK:
                    LOGIN_FAILURES.pop(ip, None)
                headers = self.login_session(db)
                db.commit()
                return self.response(200, {"ok": True}, headers=headers)
            if path == "/api/v1/report" and method == "POST":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                device = db.execute(
                    "SELECT * FROM devices WHERE token_hash=?", (digest(token),)
                ).fetchone()
                if not device:
                    return self.response(401, {"error": "设备凭证无效或已撤销"})
                report = clean_report(self.body())
                p = json.loads(device["policy"])
                now = time.time()
                state = telemetry_state(report, p, now)
                old = json.loads(device["latest"]) if device["latest"] else {}
                changes = []
                if not old:
                    changes.append("设备首次上报")
                else:
                    for field, label in [
                        ("selected_node", "当前节点"),
                        ("mode", "代理模式"),
                        ("airport", "机场"),
                        ("core_reachable", "内核连接"),
                    ]:
                        if old.get(field) != report.get(field):
                            changes.append(
                                f"{label}：{old.get(field, '—')} → {report.get(field, '—')}"
                            )
                    old_state = telemetry_state(old, p, now)
                    if old_state != state:
                        changes.append(f"代理健康：{old_state} → {state}")
                    if device["last_seen"] and now - device["last_seen"] > max(
                        90, p["report_interval"] * 3
                    ):
                        changes.append("设备恢复上报")
                for message in changes:
                    db.execute(
                        "INSERT INTO events(device_id,at,message) VALUES(?,?,?)",
                        (device["id"], now, message),
                    )
                delay = (
                    (report.get("probe") or {}).get("delay_ms")
                    if state in ("healthy", "slow", "degraded")
                    else None
                )
                db.execute(
                    "UPDATE devices SET last_seen=?,latest=? WHERE id=?",
                    (now, json.dumps(report, ensure_ascii=False), device["id"]),
                )
                db.execute(
                    "INSERT INTO reports(device_id,at,state,delay) VALUES(?,?,?,?)",
                    (device["id"], now, state, delay),
                )
                db.commit()
                return self.response(200, {"ok": True, "policy": p, "server_time": now})
            if not self.session(db):
                return self.response(401, {"error": "请先登录"})
            if path == "/api/logout" and method == "POST":
                cookie = self.headers.get("Cookie", "")
                for part in cookie.split(";"):
                    if part.strip().startswith("proxylens_session="):
                        db.execute(
                            "DELETE FROM sessions WHERE hash=?",
                            (digest(part.strip().split("=", 1)[1]),),
                        )
                db.commit()
                return self.response(
                    200, {"ok": True}, headers={"Set-Cookie": self.cookie("", 0)}
                )
            if path == "/api/devices" and method == "GET":
                now = time.time()
                devices = [
                    serialize_device(db, row, now)
                    for row in db.execute(
                        "SELECT * FROM devices ORDER BY group_name,created"
                    )
                ]
                return self.response(
                    200,
                    {
                        "devices": devices,
                        "server_time": now,
                        "public_url": PUBLIC_URL,
                        "version": "0.1.0",
                    },
                )
            if path == "/api/devices" and method == "POST":
                body = self.body()
                name = text(body.get("name", "")).strip()
                if not name:
                    raise ValueError("请填写设备名称")
                device_id, token = secrets.token_hex(8), secrets.token_urlsafe(32)
                p = policy_from(body)
                db.execute(
                    "INSERT INTO devices(id,name,group_name,allow_offline,token_hash,policy,created,notes) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        device_id,
                        name,
                        text(body.get("group", "我的设备")).strip() or "我的设备",
                        body.get("allow_offline") is True,
                        digest(token),
                        json.dumps(p),
                        time.time(),
                        text(body.get("notes", ""), 500),
                    ),
                )
                db.commit()
                return self.response(
                    201, {"id": device_id, "token": token, "policy": p}
                )
            if path.startswith("/api/devices/"):
                parts = path.strip("/").split("/")
                device_id = parts[2]
                row = db.execute(
                    "SELECT * FROM devices WHERE id=?", (device_id,)
                ).fetchone()
                if not row:
                    return self.response(404, {"error": "设备不存在"})
                if len(parts) == 4 and parts[3] == "token" and method == "POST":
                    token = secrets.token_urlsafe(32)
                    db.execute(
                        "UPDATE devices SET token_hash=? WHERE id=?",
                        (digest(token), device_id),
                    )
                    db.commit()
                    return self.response(
                        200, {"token": token, "policy": json.loads(row["policy"])}
                    )
                if len(parts) == 3 and method == "PATCH":
                    body = self.body()
                    name = text(body.get("name", "")).strip()
                    if not name:
                        raise ValueError("请填写设备名称")
                    p = policy_from(body)
                    db.execute(
                        "UPDATE devices SET name=?,group_name=?,allow_offline=?,policy=?,notes=? WHERE id=?",
                        (
                            name,
                            text(body.get("group", "我的设备")).strip() or "我的设备",
                            body.get("allow_offline") is True,
                            json.dumps(p),
                            text(body.get("notes", ""), 500),
                            device_id,
                        ),
                    )
                    db.commit()
                    return self.response(200, {"ok": True})
                if len(parts) == 3 and method == "DELETE":
                    db.execute("DELETE FROM devices WHERE id=?", (device_id,))
                    db.commit()
                    return self.response(200, {"ok": True})
            if path.startswith("/downloads/") and method == "GET":
                name = path.removeprefix("/downloads/")
                allowed = {
                    f"proxylens-agent-{system}-{arch}"
                    + (".exe" if system == "windows" else "")
                    for system in ("linux", "darwin", "windows")
                    for arch in ("amd64", "arm64")
                }
                file = DOWNLOADS / name
                if name in allowed and file.is_file():
                    return self.response(
                        200,
                        file.read_bytes(),
                        "application/octet-stream",
                        {"Content-Disposition": f'attachment; filename="{name}"'},
                    )
            return self.response(404, {"error": "接口不存在"})


def cleanup():
    while True:
        time.sleep(3600)
        with DB_LOCK, connect() as db:
            cutoff = time.time() - RETENTION_DAYS * 86400
            db.execute("DELETE FROM reports WHERE at<?", (cutoff,))
            db.execute("DELETE FROM events WHERE at<?", (cutoff,))
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    init_db()
    threading.Thread(target=cleanup, daemon=True).start()
    server = ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler
    )
    server.daemon_threads = True
    logger.info("ProxyLens 0.1.0 listening on %s", server.server_address)
    server.serve_forever()
