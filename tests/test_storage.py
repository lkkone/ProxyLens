import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, "/app")
import app


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.credentials = (app.ADMIN_USERNAME, app.ADMIN_PASSWORD)
        app.DATA = Path(self.temp.name)
        app.init_db()

    def tearDown(self):
        app.ADMIN_USERNAME, app.ADMIN_PASSWORD = self.credentials
        self.temp.cleanup()

    def test_bootstrap_and_restart_persistence(self):
        with app.connect() as db:
            username = db.execute(
                "SELECT value FROM settings WHERE key='username'"
            ).fetchone()["value"]
            old = db.execute(
                "SELECT value FROM settings WHERE key='password'"
            ).fetchone()["value"]
        self.assertEqual(username, app.ADMIN_USERNAME)
        app.init_db()
        with app.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM settings WHERE key='password'"
                ).fetchone()["value"],
                old,
            )

    def test_environment_credentials_change_revokes_sessions(self):
        import json

        with app.connect() as db:
            db.execute(
                "INSERT INTO sessions VALUES(?,?)", ("old-session", time.time() + 3600)
            )
        app.ADMIN_USERNAME = "changed-admin"
        app.ADMIN_PASSWORD = "changed-test-password"
        app.init_db()
        with app.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM settings WHERE key='username'"
                ).fetchone()["value"],
                "changed-admin",
            )
            stored = json.loads(
                db.execute(
                    "SELECT value FROM settings WHERE key='password'"
                ).fetchone()["value"]
            )
            self.assertEqual(
                stored["hash"], app.password_hash(app.ADMIN_PASSWORD, stored["salt"])
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
            )

    def test_reject_is_not_reported_as_direct(self):
        policy = app.policy_from({})
        for node in ("REJECT", "REJECT-DROP"):
            self.assertEqual(app.telemetry_state({"core_reachable": True, "mode": "rule", "selected_node": node}, policy, time.time()), "error")
        self.assertEqual(app.telemetry_state({"core_reachable": True, "mode": "direct", "selected_node": "DIRECT"}, policy, time.time()), "direct")

    def test_history_uses_actual_latest_report_and_never_current_state(self):
        import json

        bucket = int(time.time() // 300) * 300
        now = bucket + 100
        p = app.policy_from({})
        report = {"core_reachable": True, "mode": "rule", "selected_node": "HK",
                  "probe": {"ok": True, "at": now, "node": "HK", "delay_ms": 30}}
        with app.connect() as db:
            db.execute(
                "INSERT INTO devices(id,name,group_name,allow_offline,token_hash,policy,created,last_seen,latest) VALUES(?,?,?,?,?,?,?,?,?)",
                ("history", "Mac", "Office", 0, "historytoken", json.dumps(p), now, now, json.dumps(report)),
            )
            for at, state in [(bucket - 40, "error"), (bucket + 10, "error"), (bucket + 30, "healthy")]:
                db.execute("INSERT INTO heartbeats(device_id,at,state,delay) VALUES(?,?,?,?)", ("history", at, state, 30))
            row = db.execute("SELECT * FROM devices WHERE id='history'").fetchone()
            result = app.serialize_device(db, row, now)
            self.assertEqual(result["history"][-1]["state"], "healthy")
            self.assertEqual(result["history"][-1]["sample_at"], bucket + 30)
            self.assertEqual(result["history"][-2]["state"], "error")
            db.execute("DELETE FROM heartbeats WHERE device_id='history' AND at>=?", (bucket,))
            result = app.serialize_device(db, row, now)
            self.assertEqual(result["state"], "healthy")
            self.assertEqual(result["history"][-1]["state"], "error")
            self.assertEqual(result["history"][-1]["sample_at"], bucket - 40)

    def test_offline_gray_gaps_and_history_persistence(self):
        import json

        now = time.time()
        p = app.policy_from({})
        r = {
            "core_reachable": True,
            "mode": "rule",
            "selected_node": "HK",
            "probe": {"ok": True, "at": now - 3600, "node": "HK", "delay_ms": 30},
        }
        with app.connect() as db:
            db.execute(
                "INSERT INTO devices(id,name,group_name,allow_offline,token_hash,policy,created,last_seen,latest) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "device",
                    "Mac",
                    "Office",
                    1,
                    "tokenhash",
                    json.dumps(p),
                    now - 7200,
                    now - 3600,
                    json.dumps(r),
                ),
            )
            db.execute(
                "INSERT INTO reports(device_id,at,state,delay) VALUES(?,?,?,?)",
                ("device", now - 3600, "healthy", 30),
            )
            db.execute("DELETE FROM settings WHERE key='point_history_v1'")
        app.init_db()
        app.init_db()
        with app.connect() as db:
            row = db.execute("SELECT * FROM devices WHERE id='device'").fetchone()
            snapshot = app.serialize_device(db, row, now)
            self.assertEqual(snapshot["state"], "offline")
            self.assertTrue(snapshot["allow_offline"])
            self.assertEqual(len(snapshot["history"]), 1)
            self.assertEqual(snapshot["history"][-1]["state"], "healthy")
            self.assertEqual(
                sum(b["state"] == "healthy" for b in snapshot["history"]), 1
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
