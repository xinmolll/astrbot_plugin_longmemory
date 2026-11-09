import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

from write_gate import GATE, ALLOW, DENY, SKIP
import affinity as aff
import ask_alias as aa


class GateTests(unittest.TestCase):
    def test_allow_user_fact(self):
        v = GATE.judge({"text": "喜欢吃辣", "evidence": "我喜欢吃辣", "speaker": "user"})
        self.assertEqual(v.decision, ALLOW)

    def test_deny_bot(self):
        v = GATE.judge({"text": "我喜欢吃辣", "speaker": "bot", "source_type": "bot_utterance"})
        self.assertEqual(v.decision, DENY)

    def test_skip_plan(self):
        v = GATE.judge({"text": "打算明天去买书", "evidence": "打算明天去买书", "speaker": "user"})
        self.assertEqual(v.decision, SKIP)


class AffinityTests(unittest.TestCase):
    def test_no_lover_stage(self):
        names = [s["name"] for s in aff.DEFAULT_STAGES]
        self.assertNotIn("恋人", names)
        self.assertEqual(aff.stage_of(900)["name"], "亲近")

    def test_gain_slows(self):
        self.assertGreater(aff.affinity_gain(0, 800), aff.affinity_gain(700, 800))


class AliasTests(unittest.TestCase):
    def test_expand_age(self):
        keys = aa.expand_query("你多大了呀")
        self.assertTrue(any("年龄" in k or "岁" in k or "多大了" in k for k in keys))


if __name__ == "__main__":
    unittest.main()
