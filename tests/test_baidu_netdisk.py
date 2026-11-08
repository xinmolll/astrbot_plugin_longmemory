"""Unit tests for baidu_netdisk packing + mocked OAuth/upload."""
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import baidu_netdisk as bn


class PackTests(unittest.TestCase):
    def test_pack_excludes_tokens_and_includes_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "memory").mkdir()
            (root / "memory" / "u.json").write_text('{"facts":[]}', encoding="utf-8")
            (root / "chats" / "u").mkdir(parents=True)
            (root / "chats" / "u" / "2026-11-06.jsonl").write_text('{"role":"user"}\n', encoding="utf-8")
            (root / "relation").mkdir()
            (root / "relation" / "u.json").write_text('{"notes":"x"}', encoding="utf-8")
            (root / "diaries" / "u").mkdir(parents=True)
            (root / "diaries" / "u" / "2026-11-06.md").write_text("# d\n", encoding="utf-8")
            (root / "baidu_tokens.json").write_text('{"refresh_token":"SECRET"}', encoding="utf-8")
            (root / "baidu_backup_state.json").write_text('{"fail_count":0}', encoding="utf-8")
            dest = root / "out" / "astrbot-backup-2026-11-06.tar.gz"
            bn.pack_backup(root, dest, exclude_names=("baidu_tokens.json",))
            self.assertTrue(dest.exists() and dest.stat().st_size > 0)
            with tarfile.open(dest, "r:gz") as tar:
                names = set(tar.getnames())
            self.assertIn("memory/u.json", names)
            self.assertIn("chats/u/2026-11-06.jsonl", names)
            self.assertIn("relation/u.json", names)
            self.assertIn("diaries/u/2026-11-06.md", names)
            self.assertIn("baidu_backup_state.json", names)
            self.assertNotIn("baidu_tokens.json", names)
            # secret must not appear in archive bytes
            raw = dest.read_bytes()
            self.assertNotIn(b"SECRET", raw)


class OAuthMockTests(unittest.TestCase):
    def test_device_code_and_poll(self):
        calls = []

        def fake_req(url, **kwargs):
            calls.append(url)
            if "/device/code" in url:
                return {
                    "device_code": "dc1",
                    "user_code": "abcd",
                    "verification_url": "https://openapi.baidu.com/device",
                    "qrcode_url": "https://example/qr",
                    "expires_in": 300,
                    "interval": 5,
                }
            if "grant_type=device_token" in url:
                if len([u for u in calls if "device_token" in u]) < 2:
                    return {"error": "authorization_pending"}
                return {
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 2592000,
                    "scope": "basic netdisk",
                }
            raise AssertionError(url)

        sleeps = []
        with mock.patch.object(bn, "_req", side_effect=fake_req):
            info = bn.device_code("KEY")
            self.assertEqual(info["user_code"], "abcd")
            tok = bn.poll_device_token(
                "KEY", "SEC", "dc1", interval=5, expires_in=60, sleep_fn=lambda s: sleeps.append(s)
            )
        self.assertEqual(tok["access_token"], "at")
        self.assertTrue(sleeps)  # waited on pending

    def test_ensure_access_refreshes(self):
        def fake_req(url, **kwargs):
            self.assertIn("refresh_token", url)
            return {
                "access_token": "new_at",
                "refresh_token": "new_rt",
                "expires_in": 1000,
                "scope": "basic netdisk",
            }

        with mock.patch.object(bn, "_req", side_effect=fake_req):
            out = bn.ensure_access(
                {"access_token": "old", "refresh_token": "old_rt", "expires_at": 0},
                "KEY",
                "SEC",
            )
        self.assertEqual(out["access_token"], "new_at")
        self.assertEqual(out["refresh_token"], "new_rt")


class UploadMockTests(unittest.TestCase):
    def test_upload_small_file_flow(self):
        stages = {"pre": 0, "up": 0, "create": 0}

        def fake_req(url, **kwargs):
            if "method=precreate" in url:
                stages["pre"] += 1
                data = kwargs.get("form") or {}
                self.assertTrue(str(data.get("path", "")).startswith("/apps/AstrBot备份/astrbot-backup/"))
                return {"errno": 0, "uploadid": "uid1", "return_type": 1, "block_list": [0]}
            if "superfile2" in url or "method=upload" in url:
                stages["up"] += 1
                return {"md5": "x", "request_id": 1}
            if "method=create" in url:
                stages["create"] += 1
                return {"errno": 0, "path": "/apps/AstrBot备份/astrbot-backup/f.tar.gz", "size": 10}
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "astrbot-backup-2026-11-06.tar.gz"
            f.write_bytes(b"hello backup")
            with mock.patch.object(bn, "_req", side_effect=fake_req):
                res = bn.upload_file("AT", f, app_name="AstrBot备份")
        self.assertTrue(res["ok"])
        self.assertEqual(stages, {"pre": 1, "up": 1, "create": 1})

    def test_rapid_upload_skips_slices(self):
        def fake_req(url, **kwargs):
            if "precreate" in url:
                return {"errno": 0, "return_type": 2, "path": "/apps/X/astrbot-backup/a.tar.gz"}
            raise AssertionError("should not call " + url)

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.tar.gz"
            f.write_bytes(b"abc")
            with mock.patch.object(bn, "_req", side_effect=fake_req):
                res = bn.upload_file("AT", f, app_name="X")
        self.assertTrue(res["rapid"])


if __name__ == "__main__":
    unittest.main()
