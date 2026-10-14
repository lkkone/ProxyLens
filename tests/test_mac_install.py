"""Optional host integration test: installs and removes a real macOS LaunchAgent.

Requires the isolated Compose server and the ZIP downloaded by browser.cjs.
Refuses to replace an existing user installation.
"""

import json
import os
import re
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

def main():
    base = "http://localhost:18791"
    package = Path(".local/installer-qa/proxylens-darwin-arm64").resolve()
    plist = Path.home() / "Library/LaunchAgents/com.proxylens.agent.plist"
    installed = Path.home() / "Library/Application Support/ProxyLens"
    if plist.exists() or installed.exists():
        raise SystemExit("An existing installation must not be overwritten by this test.")
    client = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor()
    )


    def request(path, method="GET", body=None):
        r = client.open(
            urllib.request.Request(
                base + path,
                method=method,
                headers={"Content-Type": "application/json", "X-ProxyLens-Request": "1"},
                data=json.dumps(body).encode() if body is not None else None,
            )
        )
        return json.load(r)


    request(
        "/api/login",
        "POST",
        {"username": "likaikai", "password": "ProxyLens-isolated-test-password"},
    )
    device = request("/api/devices", "POST", {"name": "macOS installer integration"})
    config = json.loads((package / "agent.json").read_text())
    config["token"] = device["token"]
    (package / "agent.json").write_text(json.dumps(config))
    service = f"gui/{os.getuid()}/com.proxylens.agent"


    def current_pid():
        r = subprocess.run(
            ["launchctl", "print", service], capture_output=True, text=True, check=False
        )
        match = re.search(r"\bpid = (\d+)", r.stdout)
        return int(match[1]) if match else None


    try:
        subprocess.run(["bash", str(package / "install.command")], check=True)
        assert installed.is_dir() and plist.exists()
        assert (installed / "agent.json").stat().st_mode & 0o077 == 0
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            snapshot = next(
                d for d in request("/api/devices")["devices"] if d["id"] == device["id"]
            )
            if snapshot["last_seen"]:
                break
            time.sleep(1)
        else:
            raise AssertionError("Installed agent did not report")
        pid = current_pid()
        assert pid
        print(
            "User-only installation, private configuration and live reporting verified",
            flush=True,
        )
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            new_pid = current_pid()
            if new_pid and new_pid != pid:
                break
            time.sleep(1)
        else:
            raise AssertionError("LaunchAgent did not restart the process")
        print("Automatic restart after process exit verified", flush=True)
        # A repeated install replaces configuration and reloads the existing service.
        subprocess.run(["bash", str(package / "install.command")], check=True)
        deadline = time.monotonic() + 5
        while not current_pid() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert current_pid()
        print("Repeated installation verified", flush=True)
    finally:
        subprocess.run(["bash", str(package / "uninstall.command")], check=True)
        request("/api/devices/" + device["id"], "DELETE")
    assert not plist.exists() and not installed.exists() and current_pid() is None
    print("Clean uninstall verified")


if __name__ == "__main__":
    main()
