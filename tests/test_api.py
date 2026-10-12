"""Integration tests against the isolated Compose test server (never production data)."""

import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("TEST_URL", "http://localhost:18791")


class APIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor()
        )
        cls.public = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cls.password = os.environ.get(
            "TEST_PASSWORD", "ProxyLens-isolated-test-password"
        )
        status, _ = cls.request(
            "/api/login", "POST", {"username": "likaikai", "password": cls.password}
        )
        if status != 200:
            raise RuntimeError("Cannot log in to the isolated test server.")

    @classmethod
    def request(
        cls, path, method="GET", body=None, token=None, public=False, csrf=True
    ):
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-ProxyLens-Request"] = "1"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            BASE + path,
            method=method,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            r = (cls.public if public else cls.client).open(req, timeout=20)
        except urllib.error.HTTPError as e:
            r = e
        return r.status, json.load(r)

    def setUp(self):
        self.created = []

    def tearDown(self):
        for device_id in self.created:
            self.request("/api/devices/" + device_id, "DELETE")

    def device(self, **fields):
        status, d = self.request(
            "/api/devices", "POST", {"name": "Integration Device", **fields}
        )
        self.assertEqual(status, 201)
        self.created.append(d["id"])
        return d

    def report(self, **fields):
        import time

        return {
            "schema_version": 1,
            "adapter": "mihomo",
            "hostname": "test-host",
            "os": "linux",
            "arch": "amd64",
            "core_reachable": True,
            "mode": "rule",
            "selected_node": "HK",
            "primary_group": "Proxy",
            "probe": {
                "ok": True,
                "delay_ms": 50,
                "at": int(time.time()),
                "node": "HK",
                "target": "https://www.gstatic.com/generate_204",
            },
            "groups": [],
            "providers": [],
            "nodes": [],
            **fields,
        }

    def snapshot(self, device_id):
        return next(
            d
            for d in self.request("/api/status", public=True)[1]["devices"]
            if d["id"] == device_id
        )

    def test_public_status_private_management(self):
        self.assertEqual(self.request("/api/status", public=True)[0], 200)
        self.assertEqual(
            self.request(
                "/api/login",
                "POST",
                {"username": "wrong", "password": self.password},
                public=True,
            )[0],
            401,
        )
        self.assertEqual(self.request("/api/devices", public=True)[0], 401)
        self.assertEqual(
            self.request("/api/devices", "POST", {"name": "blocked"}, public=True)[0],
            401,
        )
        self.assertEqual(
            self.request("/api/devices", "POST", {"name": "blocked"}, csrf=False)[0],
            403,
        )
        self.assertEqual(
            self.request("/api/setup", "POST", {"password": "another-long-password"})[
                0
            ],
            404,
        )

    def test_device_notes_private_and_persisted(self):
        d = self.device(notes="Office device")
        devices = self.request("/api/devices")[1]["devices"]
        self.assertEqual(
            next(x for x in devices if x["id"] == d["id"])["notes"], "Office device"
        )
        self.assertNotIn("notes", self.snapshot(d["id"]))
        status, _ = self.request(
            "/api/devices/" + d["id"], "PATCH", {"name": "Edited", "notes": "New note"}
        )
        self.assertEqual(status, 200)
        devices = self.request("/api/devices")[1]["devices"]
        self.assertEqual(
            next(x for x in devices if x["id"] == d["id"])["notes"], "New note"
        )

    def test_token_binding_rotation_and_deletion(self):
        a, b = self.device(name="A"), self.device(name="B")
        r = self.report(device_id=b["id"])
        self.assertEqual(
            self.request("/api/v1/report", "POST", r, token=a["token"], public=True)[0],
            200,
        )
        self.assertEqual(self.snapshot(a["id"])["state"], "healthy")
        self.assertEqual(self.snapshot(b["id"])["state"], "pending")
        token = self.request(f"/api/devices/{a['id']}/token", "POST")[1]["token"]
        self.assertEqual(
            self.request("/api/v1/report", "POST", r, token=a["token"], public=True)[0],
            401,
        )
        self.assertEqual(
            self.request("/api/v1/report", "POST", r, token=token, public=True)[0], 200
        )
        self.request("/api/devices/" + a["id"], "DELETE")
        self.assertEqual(
            self.request("/api/v1/report", "POST", r, token=token, public=True)[0], 401
        )

    def test_delay_colors_and_worst_bin(self):
        d = self.device()
        r = self.report()
        for delay, state in [
            (300, "healthy"),
            (301, "slow"),
            (1000, "slow"),
            (1001, "degraded"),
        ]:
            r["probe"]["delay_ms"] = delay
            self.assertEqual(
                self.request(
                    "/api/v1/report", "POST", r, token=d["token"], public=True
                )[0],
                200,
            )
            snapshot = self.snapshot(d["id"])
            self.assertEqual(snapshot["state"], state)
        r["probe"]["ok"] = False
        self.request("/api/v1/report", "POST", r, token=d["token"], public=True)
        self.assertEqual(self.snapshot(d["id"])["state"], "error")
        r["probe"]["ok"] = True
        r["probe"]["delay_ms"] = 50
        self.request("/api/v1/report", "POST", r, token=d["token"], public=True)
        self.assertEqual(self.snapshot(d["id"])["state"], "healthy")
        self.assertEqual(self.snapshot(d["id"])["history"][-1]["state"], "error")

    def test_stale_mismatched_disabled_and_direct(self):
        d = self.device()
        for update, expected in [
            ({"probe": None}, "unknown"),
            ({"core_reachable": False}, "error"),
            ({"mode": "direct"}, "direct"),
        ]:
            r = self.report(**update)
            self.request("/api/v1/report", "POST", r, token=d["token"], public=True)
            self.assertEqual(self.snapshot(d["id"])["state"], expected)
        for mutate in ["node", "old", "future"]:
            r = self.report()
            if mutate == "node":
                r["probe"]["node"] = "old-node"
            if mutate == "old":
                r["probe"]["at"] -= 3600
            if mutate == "future":
                r["probe"]["at"] += 3600
            self.request("/api/v1/report", "POST", r, token=d["token"], public=True)
            self.assertEqual(self.snapshot(d["id"])["state"], "unknown")
        self.request(
            "/api/devices/" + d["id"],
            "PATCH",
            {"name": "disabled", "probe_enabled": False},
        )
        self.request(
            "/api/v1/report", "POST", self.report(), token=d["token"], public=True
        )
        self.assertEqual(self.snapshot(d["id"])["state"], "unknown")

    def test_report_allowlist_and_validation(self):
        d = self.device()
        r = self.report(
            secret="DO_NOT_STORE", token="DO_NOT_STORE", subscription_url="DO_NOT_STORE"
        )
        r["nodes"] = [
            {
                "name": "<script>alert(1)</script>",
                "type": "SS",
                "password": "DO_NOT_STORE",
                "server": "DO_NOT_STORE",
            }
        ]
        self.assertEqual(
            self.request("/api/v1/report", "POST", r, token=d["token"], public=True)[0],
            200,
        )
        snapshot = self.snapshot(d["id"])
        self.assertNotIn("DO_NOT_STORE", json.dumps(snapshot))
        self.assertNotIn("events", snapshot)
        self.assertNotIn("token_hash", snapshot)
        for invalid in [
            {"schema_version": 2},
            {"adapter": "invalid"},
            {"probe": "bad"},
            {"probe": {"delay_ms": -1}},
        ]:
            self.assertEqual(
                self.request(
                    "/api/v1/report",
                    "POST",
                    self.report(**invalid),
                    token=d["token"],
                    public=True,
                )[0],
                400,
            )
        self.assertEqual(
            self.request(
                "/api/devices",
                "POST",
                {"name": "bad", "green_delay_ms": 1000, "red_delay_ms": 300},
            )[0],
            400,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
