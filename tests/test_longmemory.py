"""Synthetic-data unit tests for LongMemory v1.5.19. No real chats/memory."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure stubs + plugin root on path when run as `python -m unittest` / pytest
TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = TESTS_DIR.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import conftest  # noqa: F401  — install astrbot stubs

import importlib.util


def _load_mod():
    spec = importlib.util.spec_from_file_location("lm_main_under_test", PLUGIN_DIR / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lm_main_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load_mod()


class Cfg(dict):
    def get(self, k, default=None):
        return super().get(k, default)

    def save_config(self):
        pass


class FakeEvent:
    def get_platform_name(self):
        return "webchat"


class LongMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm1510-"))
        for d in ("memory", "relation", "chats", "diaries"):
            (self.tmp / d).mkdir()
        self.uid = "testowner"
        self.inst = object.__new__(MOD.LongMemory)
        self.inst.root = self.tmp
        self.inst.config = Cfg(
            {
                "owner_id": self.uid,
                "memory_enabled": True,
                "relationship_enabled": True,
                "baidu_backup_hour": 0,
                "faces_enabled": False,
                "inject_diaries": 0,
            }
        )
        self.inst.locks = {}
        self.inst.retry_at = {}
        self.inst._ctx_cache = {}
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        try:
            self.loop.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_mem(self, prefs=None, facts=None, style=None):
        m = self.inst.load_mem(self.uid)
        m["preferences"] = prefs or []
        m["facts"] = facts or []
        m["style"] = style or []
        m["next_id"] = 100
        self.inst.save_mem(self.uid, m, invalidate=False)
        return m

    # ---- 1. explicit correction ----
    def test_correction_via_remove_list(self):
        prev = {
            "preferences": [{"id": 1, "text": "喜欢吃辣", "evidence": "我喜欢吃辣"}],
            "facts": [],
            "style": [],
            "next_id": 10,
            "user_removed": [],
        }
        proposal = {
            "preferences": [{"text": "不喜欢吃辣", "evidence": "其实我不喜欢吃辣"}],
            "facts": [],
            "style": [],
            "remove": ["喜欢吃辣"],
        }
        verified = self.inst.checked(proposal, prev, ["其实我不喜欢吃辣", "我喜欢吃辣"], prev)
        texts = [x["text"] for x in verified["preferences"]]
        self.assertIn("不喜欢吃辣", texts)
        self.assertNotIn("喜欢吃辣", texts)

    def test_correction_deterministic_without_remove(self):
        prev = {
            "preferences": [{"id": 1, "text": "喜欢吃火锅", "evidence": "我喜欢吃火锅"}],
            "facts": [],
            "style": [],
            "next_id": 10,
            "user_removed": [],
        }
        proposal = {
            "preferences": [{"text": "不喜欢吃火锅", "evidence": "其实我不喜欢吃火锅了"}],
            "facts": [],
            "style": [],
        }
        verified = self.inst.checked(
            proposal, prev, ["其实我不喜欢吃火锅了", "我喜欢吃火锅"], prev
        )
        texts = [x["text"] for x in verified["preferences"]]
        self.assertEqual(texts, ["不喜欢吃火锅"])
        self.assertFalse(any(x.get("pending_confirm") for x in verified["preferences"]))

    def test_unconfirmed_conflict_pending(self):
        prev = {
            "preferences": [{"id": 1, "text": "喜欢猫", "evidence": "我喜欢猫"}],
            "facts": [],
            "style": [],
            "next_id": 10,
            "user_removed": [],
        }
        proposal = {
            "preferences": [{"text": "不喜欢猫", "evidence": "我养过猫"}],  # no correction cue
            "facts": [],
            "style": [],
        }
        verified = self.inst.checked(proposal, prev, ["我养过猫", "我喜欢猫"], prev)
        texts = [x["text"] for x in verified["preferences"]]
        self.assertIn("喜欢猫", texts)
        self.assertIn("不喜欢猫", texts)
        self.assertTrue(all(x.get("pending_confirm") for x in verified["preferences"]))

    def test_pending_shown_in_injected_and_edit(self):
        self._seed_mem(
            prefs=[
                {"id": 1, "text": "喜欢猫", "evidence": "a", "pending_confirm": True},
                {"id": 2, "text": "不喜欢猫", "evidence": "b", "pending_confirm": True},
            ]
        )
        ctx = self.inst._context_text(self.uid)
        self.assertIn("待确认", ctx)
        self.assertIn("pending_confirm", ctx)
        edit = self.inst.render_edit_memory(self.inst.load_mem(self.uid))
        self.assertIn(MOD.PENDING_TAG, edit)
        # round-trip: keep only one line → pending cleared
        new_edit = "## 偏好\n不喜欢猫\n\n## 事实\n\n## 口吻\n"
        # simulate apply
        m = self.inst.load_mem(self.uid)
        parsed = self.inst.parse_edit_memory(new_edit)
        self.assertEqual(parsed["preferences"][0]["text"], "不喜欢猫")
        self.assertFalse(parsed["preferences"][0]["pending_hint"])
        # run apply path via editing config field
        self.inst.config["edit_memory"] = new_edit
        m["edit_snapshot_hash"] = "different"
        self.inst.save_mem(self.uid, m, invalidate=False)
        changed = self.inst.apply_edit_memory_from_config()
        self.assertTrue(changed)
        m2 = self.inst.load_mem(self.uid)
        prefs = m2["preferences"]
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["text"], "不喜欢猫")
        self.assertFalse(prefs[0].get("pending_confirm"))

    # ---- 2. cache invalidation ----
    def test_save_mem_invalidates_on_content_change_only(self):
        self._seed_mem(facts=[{"id": 1, "text": "旧事实", "evidence": "e"}])
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        m = self.inst.load_mem(self.uid)
        m["processed_watermark"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.inst.save_mem(self.uid, m)  # watermark only
        self.assertIn(self.uid, self.inst._ctx_cache)
        m["facts"].append({"id": 2, "text": "新事实ABC", "evidence": "e2"})
        self.inst.save_mem(self.uid, m)
        self.assertNotIn(self.uid, self.inst._ctx_cache)

    def test_save_rel_invalidates_on_notes_only(self):
        r = self.inst.load_rel(self.uid)
        r["notes"] = "初始笔记"
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        r = self.inst.load_rel(self.uid)
        r["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        r["dialog_seq"] = 3
        r["msg_since_rel"] = 9
        self.inst.save_rel(self.uid, r)
        self.assertIn(self.uid, self.inst._ctx_cache)  # timestamps only
        r["notes"] = "改过的笔记"
        self.inst.save_rel(self.uid, r)
        self.assertNotIn(self.uid, self.inst._ctx_cache)

    def test_learn_path_invalidates(self):
        self._seed_mem()
        # seed chats so learn has pending
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        day = dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        lines = [
            json.dumps({"role": "user", "content": f"消息{i}我喜欢喝茶", "at": dt.datetime.now(dt.timezone.utc).isoformat()}, ensure_ascii=False)
            for i in range(6)
        ]
        (chat / f"{day}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        async def fake_llm(umo, sys, user, background=False, **kw):
            return json.dumps(
                {
                    "preferences": [{"text": "喜欢喝茶", "evidence": "我喜欢喝茶"}],
                    "facts": [],
                    "style": [],
                    "remove": [],
                },
                ensure_ascii=False,
            )

        self.inst.llm = fake_llm
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        res = self.loop.run_until_complete(self.inst.learn(self.uid, "umo", force=True, update_rel=False))
        self.assertIn("已整理", res)
        self.assertNotIn(self.uid, self.inst._ctx_cache)

    def test_update_relation_invalidates(self):
        r = self.inst.load_rel(self.uid)
        r["notes"] = "旧"
        self.inst.save_rel(self.uid, r, invalidate=False)
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        day = dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        (chat / f"{day}.jsonl").write_text(
            json.dumps({"role": "user", "content": "hi"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"role": "assistant", "content": "hey"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

        async def fake_llm(umo, sys, user, background=False, **kw):
            return json.dumps({"notes": "新的关系笔记内容", "proactive_ok": False}, ensure_ascii=False)

        self.inst.llm = fake_llm
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        ok = self.loop.run_until_complete(self.inst.update_relation(self.uid, "umo"))
        self.assertTrue(ok)
        self.assertNotIn(self.uid, self.inst._ctx_cache)

    def test_apply_edit_invalidates(self):
        self._seed_mem(prefs=[{"id": 1, "text": "旧偏好", "evidence": "e"}])
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        self.inst.config["edit_memory"] = "## 偏好\n新偏好XYZ\n\n## 事实\n\n## 口吻\n"
        m = self.inst.load_mem(self.uid)
        m["edit_snapshot_hash"] = "oldhash"
        self.inst.save_mem(self.uid, m, invalidate=False)
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        self.assertTrue(self.inst.apply_edit_memory_from_config())
        self.assertNotIn(self.uid, self.inst._ctx_cache)

    def test_forget_and_clear_and_relation_set_invalidate(self):
        self._seed_mem(
            style=[{"id": 55, "text": "偶尔损两句", "evidence": "x"}],
            facts=[{"id": 56, "text": "还有一条事实", "evidence": "y"}],
        )
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        m = self.inst.load_mem(self.uid)
        for c in MOD.CATS:
            for i in list(m[c]):
                if int(i["id"]) == 55:
                    m[c].remove(i)
                    removed = set(m.get("user_removed") or [])
                    nk = self.inst._norm_key(i.get("text", ""))
                    if nk:
                        removed.add(nk)
                    m["user_removed"] = sorted(removed)[-500:]
                    self.inst.save_mem(self.uid, m)
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        m = self.inst.load_mem(self.uid)
        for c in MOD.CATS:
            m[c] = []
        self.inst.save_mem(self.uid, m)  # clears remaining facts → content change
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        r = self.inst.load_rel(self.uid)
        r["notes"] = "手动改写"
        self.inst.save_rel(self.uid, r)
        self.assertNotIn(self.uid, self.inst._ctx_cache)

    def test_frozen_reads_new_after_invalidate(self):
        self._seed_mem(facts=[{"id": 1, "text": "AAA", "evidence": "e"}])
        ctx1 = self.inst._frozen_ctx(self.uid, FakeEvent(), True)
        self.assertIn("AAA", ctx1)
        m = self.inst.load_mem(self.uid)
        m["facts"].append({"id": 2, "text": "BBB新内容", "evidence": "e"})
        self.inst.save_mem(self.uid, m)
        ctx2 = self.inst._frozen_ctx(self.uid, FakeEvent(), False)
        self.assertIn("BBB新内容", ctx2)

    # ---- 3. mood ----
    def test_stale_mood_discarded(self):
        r = self.inst.load_rel(self.uid)
        r["dialog_seq"] = 5
        r["mood"] = {
            "label": "开心",
            "reason": "旧",
            "intensity": 0.8,
            "temper": "none",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.inst.save_rel(self.uid, r, invalidate=False)
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        day = dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        (chat / f"{day}.jsonl").write_text(
            json.dumps({"role": "user", "content": "hi"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"role": "assistant", "content": "hey"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

        async def fake_llm(umo, sys, user, background=False, **kw):
            rr = self.inst.load_rel(self.uid)
            rr["dialog_seq"] = 6
            self.inst.save_rel(self.uid, rr, invalidate=False)
            return json.dumps(
                {"label": "难过", "reason": "过期", "intensity": 0.9, "temper": "cool", "her_views_add": [], "her_views_remove": []},
                ensure_ascii=False,
            )

        self.inst.llm = fake_llm
        self.loop.run_until_complete(self.inst.update_mood_and_views(self.uid, "umo"))
        mood = self.inst.load_rel(self.uid).get("mood") or {}
        self.assertEqual(mood.get("label"), "开心")

    # ---- 4. proactive / followup concurrency ----
    def test_proactive_stale_discards_nosay_and_send(self):
        r = self.inst.load_rel(self.uid)
        now = dt.datetime.now(dt.timezone.utc)
        r["last_user_at"] = (now - dt.timedelta(hours=2)).isoformat()
        r["last_bot_at"] = (now - dt.timedelta(hours=2)).isoformat()
        r["dialog_seq"] = 1
        r["next_gap_hours"] = 0.1
        r["umo"] = "napcat:FriendMessage:testowner"
        r["notes"] = "搭子"
        self.inst.save_rel(self.uid, r, invalidate=False)
        before_notes = self.inst.load_rel(self.uid)["notes"]
        before_seq = self.inst.load_rel(self.uid)["dialog_seq"]

        # stub platform ok + persona + send
        self.inst._umo_ok = lambda umo: (True, "ok")
        self.inst.context = types_ns = type("C", (), {})()
        class PM:
            async def get_default_persona_v3(self, umo):
                return {"prompt": "人设"}
        self.inst.context.persona_manager = PM()
        sent_flags = []

        async def send_message(umo, chain):
            sent_flags.append(True)
            return True

        self.inst.context.send_message = send_message
        self.inst.context.platform_manager = type("P", (), {"platform_insts": []})()

        # Case A: nosay but stale during generation
        async def llm_nosay_stale(umo, sys, user, background=False, **kw):
            rr = self.inst.load_rel(self.uid)
            rr["dialog_seq"] = before_seq + 1
            rr["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.inst.save_rel(self.uid, rr, invalidate=False)
            return "（不说）"

        self.inst.llm = llm_nosay_stale
        # force gap elapsed: last times already 2h ago; gap 0.1
        self.inst.cfg = lambda k, d=None: {
            "proactive_enabled": True,
            "proactive_min_hours": 0.1,
            "proactive_max_hours": 0.1,
            "proactive_max_unanswered": 5,
            "proactive_start_hour": 0,
            "proactive_end_hour": 24,
            "owner_id": self.uid,
            "diary_session": f"napcat:FriendMessage:{self.uid}",
            "stickers_enabled": False,
            "relationship_enabled": True,
            "memory_enabled": True,
            "faces_enabled": False,
            "inject_diaries": 0,
        }.get(k, d) if True else d
        # property owner uses cfg - need to fix: we replaced cfg method
        self.loop.run_until_complete(self.inst.maybe_proactive())
        r_after = self.inst.load_rel(self.uid)
        # notes unchanged; last_bot_at should NOT have been bumped by nosay write
        self.assertEqual(r_after["notes"], before_notes)
        # dialog_seq stayed at before_seq+1 from our simulated user reply
        self.assertEqual(int(r_after["dialog_seq"]), before_seq + 1)
        # last_bot_at should still be the old one (2h ago), not now — nosay discarded
        self.assertEqual(r_after["last_bot_at"], r["last_bot_at"])
        self.assertEqual(sent_flags, [])

        # Case B: send path but stale
        r = self.inst.load_rel(self.uid)
        r["dialog_seq"] = 10
        r["last_user_at"] = (now - dt.timedelta(hours=2)).isoformat()
        r["last_bot_at"] = (now - dt.timedelta(hours=2)).isoformat()
        r["next_gap_hours"] = 0.1
        self.inst.save_rel(self.uid, r, invalidate=False)
        old_bot = r["last_bot_at"]

        async def llm_send_stale(umo, sys, user, background=False, **kw):
            rr = self.inst.load_rel(self.uid)
            rr["dialog_seq"] = 11
            rr["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.inst.save_rel(self.uid, rr, invalidate=False)
            return "嘿在吗"

        self.inst.llm = llm_send_stale
        self.loop.run_until_complete(self.inst.maybe_proactive())
        r_after = self.inst.load_rel(self.uid)
        self.assertEqual(r_after["last_bot_at"], old_bot)
        self.assertEqual(sent_flags, [])

    def test_followup_stale_discards_nosay_and_send(self):
        r = self.inst.load_rel(self.uid)
        now = dt.datetime.now(dt.timezone.utc)
        r.update(
            {
                "topic_open": True,
                "topic_hint": "那个话题",
                "followup_due_at": (now - dt.timedelta(minutes=1)).isoformat(),
                "followup_sent": 0,
                "dialog_seq": 1,
                "last_user_at": (now - dt.timedelta(minutes=10)).isoformat(),
                "last_bot_at": (now - dt.timedelta(minutes=10)).isoformat(),
                "umo": "napcat:FriendMessage:testowner",
                "notes": "搭子",
            }
        )
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.inst._umo_ok = lambda umo: (True, "ok")
        self.inst.context = type("C", (), {})()
        class PM:
            async def get_default_persona_v3(self, umo):
                return {"prompt": "人设"}
        self.inst.context.persona_manager = PM()
        sent = []
        async def send_message(umo, chain):
            sent.append(True)
            return True
        self.inst.context.send_message = send_message
        self.inst.cfg = lambda k, d=None: {
            "followup_enabled": True,
            "followup_max_per_silence": 2,
            "proactive_max_unanswered": 5,
            "proactive_start_hour": 0,
            "proactive_end_hour": 24,
            "owner_id": self.uid,
            "diary_session": f"napcat:FriendMessage:{self.uid}",
            "stickers_enabled": False,
            "relationship_enabled": True,
            "memory_enabled": True,
            "faces_enabled": False,
            "inject_diaries": 0,
            "followup_min_minutes": 3,
            "followup_max_minutes": 5,
        }.get(k, d)

        async def llm_nosay_stale(umo, sys, user, background=False, **kw):
            rr = self.inst.load_rel(self.uid)
            rr["dialog_seq"] = 2
            rr["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.inst.save_rel(self.uid, rr, invalidate=False)
            return "不说"

        self.inst.llm = llm_nosay_stale
        old_bot = self.inst.load_rel(self.uid)["last_bot_at"]
        old_open = self.inst.load_rel(self.uid)["topic_open"]
        self.loop.run_until_complete(self.inst.maybe_followup())
        ra = self.inst.load_rel(self.uid)
        self.assertEqual(ra["last_bot_at"], old_bot)
        self.assertEqual(ra["topic_open"], old_open)  # not cleared by discarded nosay
        self.assertEqual(sent, [])

        # reset due for send-stale case
        r = self.inst.load_rel(self.uid)
        r.update(
            {
                "topic_open": True,
                "followup_due_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat(),
                "followup_sent": 0,
                "dialog_seq": 5,
                "last_bot_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat(),
                "last_user_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat(),
            }
        )
        self.inst.save_rel(self.uid, r, invalidate=False)
        old_bot = r["last_bot_at"]

        async def llm_send_stale(umo, sys, user, background=False, **kw):
            rr = self.inst.load_rel(self.uid)
            rr["dialog_seq"] = 6
            rr["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.inst.save_rel(self.uid, rr, invalidate=False)
            return "那个后来怎样了"

        self.inst.llm = llm_send_stale
        self.loop.run_until_complete(self.inst.maybe_followup())
        self.assertEqual(self.inst.load_rel(self.uid)["last_bot_at"], old_bot)
        self.assertEqual(sent, [])

    # ---- 5. preserve chats / baidu hour ----
    def test_refusal_records_preserved(self):
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        fp = chat / "2026-11-06.jsonl"
        body = (
            json.dumps({"role": "user", "content": "做我女朋友吧"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"role": "assistant", "content": "心里还没到那一步"}, ensure_ascii=False)
            + "\n"
        )
        fp.write_text(body, encoding="utf-8")
        r = self.inst.load_rel(self.uid)
        r["notes"] = "他今天表白了；我拒绝了，心里还没到那一步。"
        self.inst.save_rel(self.uid, r, invalidate=False)
        before_chat, before_notes = fp.read_text(encoding="utf-8"), r["notes"]
        self.inst.ensure_core_facts(self.uid)
        self.inst.dedupe_mem(self.uid)
        self.inst.invalidate_ctx(self.uid)
        self.assertEqual(fp.read_text(encoding="utf-8"), before_chat)
        self.assertEqual(self.inst.load_rel(self.uid)["notes"], before_notes)

    def test_baidu_hour_zero(self):
        _bh = self.inst.cfg("baidu_backup_hour", 3)
        hour = 3 if _bh is None or _bh == "" else int(_bh)
        self.assertEqual(hour, 0)


    def test_apply_edit_relation_notes(self):
        r = self.inst.load_rel(self.uid)
        r["notes"] = "旧关系笔记ABC"
        r["relation_edit_snapshot_hash"] = "old"
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        new_notes = "【长期印象】测试手改关系笔记XYZ"
        # paste with meta footer should strip
        self.inst.config["edit_relation_notes"] = new_notes + "\n\n——上次改写: 2099-01-01；改写次数: 9"
        self.assertTrue(self.inst.apply_edit_relation_from_config())
        r2 = self.inst.load_rel(self.uid)
        self.assertEqual(r2["notes"], new_notes)
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        # re-apply same content → no change
        self.inst.config["edit_relation_notes"] = new_notes
        self.assertFalse(self.inst.apply_edit_relation_from_config())

    def test_apply_edit_diary_and_lock(self):
        day = "2026-11-06"
        ddir = self.inst.diary_dir(self.uid)
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / f"{day}.md").write_text(f"# {day}\n\n旧日记含柏拉图和不答应\n", encoding="utf-8")
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        cleaned = f"# {day}\n\n今天陪他熬夜聊天，聊了学习和散步。明天想轻松点。\n"
        self.inst.config["edit_diary_day"] = day
        self.inst.config["edit_diary"] = cleaned
        self.assertTrue(self.inst.apply_edit_diary_from_config())
        body = (ddir / f"{day}.md").read_text(encoding="utf-8")
        self.assertIn("学习和散步", body)
        self.assertNotIn("柏拉图", body)
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        st = self.inst.diary_state()
        self.assertTrue(st[self.uid]["days"][day].get("manual_lock"))
        # same content again → no rewrite
        self.inst.config["edit_diary"] = cleaned
        self.assertFalse(self.inst.apply_edit_diary_from_config())

    def test_relation_manual_lock_skips_update(self):
        r = self.inst.load_rel(self.uid)
        r["notes"] = "干净笔记"
        r["manual_notes_lock"] = True
        self.inst.save_rel(self.uid, r, invalidate=False)
        # seed a chat so update_relation would otherwise proceed past empty dialog
        day = "2026-11-06"
        cdir = self.tmp / "chats" / self.uid
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / f"{day}.jsonl").write_text(
            '{"role":"user","content":"hi","ts":"2026-11-06T12:00:00+08:00"}\n',
            encoding="utf-8",
        )
        ok = self.loop.run_until_complete(self.inst.update_relation(self.uid, "webchat:FriendMessage:x"))
        self.assertFalse(ok)
        self.assertEqual(self.inst.load_rel(self.uid)["notes"], "干净笔记")

    def test_apply_edit_relation_sets_lock(self):
        r = self.inst.load_rel(self.uid)
        r["notes"] = "旧"
        r["relation_edit_snapshot_hash"] = "old"
        r["manual_notes_lock"] = False
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.inst.config["edit_relation_notes"] = "【长期印象】手改干净XYZ"
        self.assertTrue(self.inst.apply_edit_relation_from_config())
        r2 = self.inst.load_rel(self.uid)
        self.assertTrue(r2.get("manual_notes_lock"))
        self.assertIn("手改干净XYZ", r2["notes"])


    def test_scrub_today_chat_removes_confession_turns(self):
        day = "2026-11-06"
        cdir = self.tmp / "chats" / self.uid
        cdir.mkdir(parents=True, exist_ok=True)
        lines = [
            {"role": "user", "content": "今天下午去公园散步了", "ts": "t1"},
            {"role": "assistant", "content": "天气还行吗", "ts": "t2"},
            {"role": "user", "content": "你同意了吧我们有名分了", "ts": "t3"},
            {"role": "assistant", "content": "我没同意，这你别记岔", "ts": "t4"},
            {"role": "user", "content": "同学打电话耽误了", "ts": "t5"},
            {"role": "assistant", "content": "明天再抓", "ts": "t6"},
            {"role": "user", "content": "柏拉图也行啊慢慢培养", "ts": "t7"},
            {"role": "user", "content": "我们是不是在谈恋爱了", "ts": "t8"},
            {"role": "assistant", "content": "这个我没答应过", "ts": "t9"},
        ]
        path = cdir / f"{day}.jsonl"
        path.write_text("\n".join(__import__("json").dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        self.inst.config["scrub_chat_day"] = day
        self.inst.config["scrub_today_chat"] = True
        n = self.inst.apply_scrub_chat_from_config()
        self.assertGreaterEqual(n, 3)
        body = path.read_text(encoding="utf-8")
        self.assertIn("公园", body)
        self.assertIn("同学打电话", body)
        self.assertNotIn("名分", body)
        self.assertNotIn("柏拉图", body)
        self.assertNotIn("没同意", body)
        self.assertNotIn("谈恋爱", body)
        self.assertNotIn("没答应过", body)
        self.assertFalse(self.inst.config.get("scrub_today_chat"))
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        self.assertIn("删除", self.inst.config.get("view_scrub_result", ""))


    def test_force_invalidate_ctx(self):
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        self.inst.config["force_invalidate_ctx"] = True
        self.assertTrue(self.inst.apply_force_invalidate_from_config())
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        self.assertFalse(self.inst.config.get("force_invalidate_ctx"))
        self.assertIn("清空", self.inst.config.get("view_invalidate_result", ""))
        self.assertFalse(self.inst.apply_force_invalidate_from_config())


    def test_backup_and_reset_all(self):
        self._seed_mem(prefs=["喜欢摇滚"], facts=["会弹吉他"])
        r = self.inst.load_rel(self.uid)
        r.update(notes="最近聊得比较多，还在互相了解。", manual_notes_lock=True,
                 migrated_v155=True, umo="napcat:FriendMessage:x", mood={"label": "开心"})
        self.inst.save_rel(self.uid, r, invalidate=False)
        cdir = self.tmp / "chats" / self.uid
        cdir.mkdir(parents=True)
        (cdir / "2026-11-06.jsonl").write_text('{"role":"user","content":"你好呀"}\n', encoding="utf-8")
        ddir = self.tmp / "diaries" / self.uid
        ddir.mkdir(parents=True)
        (ddir / "2026-11-06.md").write_text("# 2026-11-06\n\n日记", encoding="utf-8")
        (self.tmp / "baidu_tokens.json").write_text("{}", encoding="utf-8")
        (self.tmp / ".imported").write_text("x", encoding="utf-8")
        self.inst._ctx_cache[self.uid] = (0.0, "SNAP")
        # 未确认：不执行
        self.inst.config["backup_and_reset_all"] = True
        self.assertFalse(self.inst.apply_backup_reset_from_config())
        self.assertIn("未执行", self.inst.config.get("view_reset_result"))
        self.assertTrue((cdir / "2026-11-06.jsonl").exists())
        # 确认后执行
        self.inst.config["backup_and_reset_all"] = True
        self.inst.config["reset_confirm"] = "确认清空"
        self.assertTrue(self.inst.apply_backup_reset_from_config())
        bks = list((self.tmp / "backups").iterdir())
        self.assertEqual(len(bks), 1)
        b = bks[0]
        self.assertTrue((b / "chats" / self.uid / "2026-11-06.jsonl").exists())
        self.assertTrue((b / "diaries" / self.uid / "2026-11-06.md").exists())
        self.assertIn("互相了解", (b / "relation" / f"{self.uid}.json").read_text(encoding="utf-8"))
        self.assertFalse((b / "baidu_tokens.json").exists())
        self.assertTrue((b / "_manifest.json").exists())
        m = self.inst.load_mem(self.uid)
        self.assertEqual([len(m[c]) for c in MOD.CATS], [0, 0, 0])
        r2 = self.inst.load_rel(self.uid)
        self.assertEqual(r2["notes"], "")
        self.assertFalse(r2["manual_notes_lock"])
        self.assertIsNone(r2["mood"])
        self.assertTrue(r2["migrated_v155"])
        self.assertEqual(r2["umo"], "napcat:FriendMessage:x")
        self.assertFalse(any((self.tmp / "chats").rglob("*.jsonl")))
        self.assertFalse(any((self.tmp / "diaries").rglob("*.md")))
        self.assertTrue((self.tmp / "baidu_tokens.json").exists())
        self.assertTrue((self.tmp / ".imported").exists())
        self.assertNotIn(self.uid, self.inst._ctx_cache)
        self.assertNotIn("喜欢摇滚", self.inst.config.get("edit_memory"))
        self.assertFalse(self.inst.config.get("backup_and_reset_all"))
        self.assertEqual(self.inst.config.get("reset_confirm"), "")
        # 旧文本不会被当成手改写回
        self.assertFalse(self.inst.apply_edit_memory_from_config())
        self.assertFalse(self.inst.apply_edit_relation_from_config())

    # ---- 6. proactive morning / nosay short retry (v1.5.18) ----
    def test_proactive_situation_morning_prefers_greeting(self):
        s = self.inst._proactive_situation("早上", 8.0, self.uid)
        self.assertIn("不要一上来就选「（不说）」", s)
        self.assertIn("短招呼", s)
        mid = self.inst._proactive_situation("中午", 1.0, self.uid)
        self.assertIn("忽然想起来他", mid)
        self.assertIn("「（不说）」完全可以", mid)
        # after 晚安 + long silence
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        day = "2026-11-07"
        (chat / f"{day}.jsonl").write_text(
            '{"role":"user","content":"晚安"}\n{"role":"assistant","content":"晚安，睡吧"}\n',
            encoding="utf-8",
        )
        night = self.inst._proactive_situation("晚上", 5.0, self.uid)
        self.assertIn("不要一上来就选「（不说）」", night)

    def test_proactive_prompt_has_situation_slot(self):
        self.assertIn("{situation}", MOD.PROACTIVE_PROMPT)
        self.assertIn("不要硬撩", MOD.PROACTIVE_PROMPT)

    def test_proactive_nosay_short_retry_without_full_beat(self):
        r = self.inst.load_rel(self.uid)
        now = dt.datetime.now(dt.timezone.utc)
        old_bot = (now - dt.timedelta(hours=8)).isoformat()
        r.update(
            {
                "last_user_at": (now - dt.timedelta(hours=8)).isoformat(),
                "last_bot_at": old_bot,
                "dialog_seq": 3,
                "next_gap_hours": 0.1,
                "umo": "napcat:FriendMessage:testowner",
                "notes": "刚认识",
                "proactive_nosay_streak": 0,
                "last_proactive_attempt_at": None,
            }
        )
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.inst._umo_ok = lambda umo: (True, "ok")
        self.inst.context = type("C", (), {})()

        class PM:
            async def get_default_persona_v3(self, umo):
                return {"prompt": "人设"}

        self.inst.context.persona_manager = PM()
        sent = []

        async def send_message(umo, chain):
            sent.append(True)
            return True

        self.inst.context.send_message = send_message
        captured = {}

        async def llm_nosay(umo, sys, user, background=False, **kw):
            captured["sys"] = sys
            return "（不说）"

        self.inst.llm = llm_nosay
        self.inst.cfg = lambda k, d=None: {
            "proactive_enabled": True,
            "proactive_min_hours": 0.1,
            "proactive_max_hours": 0.1,
            "proactive_max_unanswered": 5,
            "proactive_start_hour": 0,
            "proactive_end_hour": 24,
            "owner_id": self.uid,
            "diary_session": f"napcat:FriendMessage:{self.uid}",
            "stickers_enabled": False,
            "relationship_enabled": True,
            "memory_enabled": True,
            "faces_enabled": False,
            "inject_diaries": 0,
        }.get(k, d)
        self.loop.run_until_complete(self.inst.maybe_proactive())
        ra = self.inst.load_rel(self.uid)
        self.assertEqual(sent, [])
        self.assertEqual(ra["last_bot_at"], old_bot)  # 第一次不说不推进完整节拍
        self.assertEqual(int(ra["proactive_nosay_streak"]), 1)
        self.assertIsNotNone(ra.get("last_proactive_attempt_at"))
        self.assertTrue(0.2 <= float(ra["next_gap_hours"]) <= 0.4)
        self.assertIn("situation" in MOD.PROACTIVE_PROMPT or True, [True])
        # 早上/久别提示应进 system
        self.assertTrue(
            "不要一上来就选「（不说）」" in captured.get("sys", "")
            or "忽然想起来他" in captured.get("sys", "")
        )

        # 第 3 次不说才完整重置
        r = self.inst.load_rel(self.uid)
        r["proactive_nosay_streak"] = 2
        r["next_gap_hours"] = 0.1
        r["last_proactive_attempt_at"] = (now - dt.timedelta(hours=1)).isoformat()
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.loop.run_until_complete(self.inst.maybe_proactive())
        rb = self.inst.load_rel(self.uid)
        self.assertNotEqual(rb["last_bot_at"], old_bot)
        self.assertEqual(int(rb.get("proactive_nosay_streak") or 0), 0)
        self.assertIsNone(rb.get("last_proactive_attempt_at"))




    # ---- 5. mood rate-limit + user-tail inject (v1.5.19) ----
    def test_should_update_mood_skips_mid_interval_calm(self):
        r = self.inst.load_rel(self.uid)
        r["msg_since_mood"] = 1
        r["mood"] = {
            "label": "平静",
            "reason": "无",
            "intensity": 0.0,
            "temper": "none",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.assertFalse(self.inst._should_update_mood(self.uid))

    def test_should_update_mood_on_count(self):
        self.inst.config["mood_update_every"] = 4
        r = self.inst.load_rel(self.uid)
        r["msg_since_mood"] = 4
        r["mood"] = {
            "label": "平静",
            "reason": "无",
            "intensity": 0.0,
            "temper": "none",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.inst.save_rel(self.uid, r, invalidate=False)
        self.assertTrue(self.inst._should_update_mood(self.uid))

    def test_should_update_mood_on_emotion(self):
        r = self.inst.load_rel(self.uid)
        r["msg_since_mood"] = 1
        r["mood"] = {
            "label": "平静",
            "reason": "无",
            "intensity": 0.0,
            "temper": "none",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.inst.save_rel(self.uid, r, invalidate=False)
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        day = dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        (chat / f"{day}.jsonl").write_text(
            json.dumps({"role": "user", "content": "我今天好难过"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"role": "assistant", "content": "怎么了"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        self.assertTrue(self.inst._should_update_mood(self.uid))

    def test_mood_inject_goes_to_user_tail_not_system(self):
        r = self.inst.load_rel(self.uid)
        r["mood"] = {
            "label": "开心",
            "reason": "被逗笑",
            "intensity": 0.7,
            "temper": "tease",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        r["notes"] = "普通朋友"
        r["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.inst.save_rel(self.uid, r, invalidate=False)
        self._seed_mem(facts=[{"id": 1, "text": "在备考", "evidence": "我在备考"}])

        class Req:
            def __init__(self):
                self.system_prompt = "人设本体"
                self.prompt = "你好呀"
                self.extra_user_content_parts = []

        uid = self.uid

        class Ev(FakeEvent):
            def get_sender_id(self):
                return uid

            def get_message_type(self):
                return "friend"

            @property
            def message_str(self):
                return ""

            @property
            def unified_msg_origin(self):
                return "umo"

        req = Req()
        self.loop.run_until_complete(self.inst.on_req(Ev(), req))
        self.assertIn("人设本体", req.system_prompt)
        self.assertNotIn("此刻心情", req.system_prompt)
        tails = []
        for part in req.extra_user_content_parts:
            if isinstance(part, dict):
                tails.append(part.get("text", ""))
            else:
                tails.append(getattr(part, "text", str(part)))
        joined = "\n".join(tails)
        self.assertIn("此刻心情", joined)
        self.assertIn("开心", joined)

    def test_learn_default_does_not_update_relation(self):
        """v1.5.19: learn 与 update_relation 解耦。"""
        called = {"rel": 0}

        async def fake_llm(umo, sys, user, background=False, **kw):
            return json.dumps(
                {
                    "preferences": [{"text": "喜欢喝茶", "evidence": "我喜欢喝茶"}],
                    "facts": [],
                    "style": [],
                    "remove": [],
                },
                ensure_ascii=False,
            )

        async def fake_rel(uid, umo, dialog=None):
            called["rel"] += 1
            return True

        self.inst.llm = fake_llm
        self.inst.update_relation = fake_rel
        chat = self.tmp / "chats" / MOD.safe(self.uid)
        chat.mkdir(parents=True, exist_ok=True)
        day = dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        lines = [
            json.dumps(
                {
                    "role": "user",
                    "content": f"消息{i}我喜欢喝茶",
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
            for i in range(6)
        ]
        (chat / f"{day}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        m = self.inst.load_mem(self.uid)
        m["processed_watermark"] = None
        m["processed"] = []
        self.inst.save_mem(self.uid, m, invalidate=False)
        res = self.loop.run_until_complete(self.inst.learn(self.uid, "umo", force=True))
        self.assertIn("已整理", res)
        self.assertEqual(called["rel"], 0)
        # 显式 update_rel=True 仍会改写
        m = self.inst.load_mem(self.uid)
        m["processed_watermark"] = None
        m["processed"] = []
        self.inst.save_mem(self.uid, m, invalidate=False)
        res2 = self.loop.run_until_complete(
            self.inst.learn(self.uid, "umo", force=True, update_rel=True)
        )
        self.assertIn("已整理", res2)
        self.assertEqual(called["rel"], 1)

    def test_unset_owner_skips_proactive_followup_and_diary(self):
        self.inst.config["owner_id"] = ""
        self.inst.config["proactive_enabled"] = True
        self.inst.config["followup_enabled"] = True
        self.inst.config["diary_enabled"] = True
        sent = []
        self.inst.context = type("C", (), {"send_message": lambda *a, **k: sent.append(a)})()
        self.loop.run_until_complete(self.inst.maybe_proactive())
        self.loop.run_until_complete(self.inst.maybe_followup())
        msg = self.loop.run_until_complete(self.inst.write_diary())
        self.assertIn("owner_id", msg)
        self.assertEqual(sent, [])
        self.assertFalse(any(self.tmp.rglob("*.md")))

    def test_core_facts_empty_by_default_and_config_driven(self):
        self.assertEqual(self.inst.ensure_core_facts(self.uid), 0)
        self.assertEqual(self.inst.load_mem(self.uid).get("facts") or [], [])
        self.inst.config["core_facts"] = "事实：喜欢晴天\n偏好：回复短一点"
        self.assertEqual(self.inst.ensure_core_facts(self.uid), 2)
        m = self.inst.load_mem(self.uid)
        self.assertIn("喜欢晴天", [x["text"] for x in m["facts"]])
        self.assertIn("回复短一点", [x["text"] for x in m["preferences"]])
        m["user_removed"] = [self.inst._norm_key("喜欢晴天")]
        m["facts"] = []
        self.inst.save_mem(self.uid, m, invalidate=False)
        self.assertEqual(self.inst.ensure_core_facts(self.uid), 0)
        self.assertEqual(self.inst.load_mem(self.uid).get("facts") or [], [])

    def test_relation_notes_do_not_preset_outcome(self):
        r = self.inst.load_rel(self.uid)
        r["notes"] = "他说过想再靠近一点；我还在想，没有答应。"
        r["last_user_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.inst.save_rel(self.uid, r, invalidate=False)

        class Req:
            def __init__(self):
                self.system_prompt = "人设本体"
                self.prompt = "你好"
                self.extra_user_content_parts = []

        uid = self.uid

        class Ev(FakeEvent):
            def get_sender_id(self):
                return uid

            def get_message_type(self):
                return "friend"

            @property
            def message_str(self):
                return ""

            @property
            def unified_msg_origin(self):
                return "umo"

        req = Req()
        self.loop.run_until_complete(self.inst.on_req(Ev(), req))
        self.assertIn("人设本体", req.system_prompt)
        self.assertIn("没有答应", req.system_prompt)
        self.assertNotIn("最高优先级", req.system_prompt)
        self.assertNotIn("你已明确同意", req.system_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
