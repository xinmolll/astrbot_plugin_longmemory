"""写入门控：纯规则 allow / deny / skip，零 LLM。
适配 longmemory：无 L3 层时，转述/RP/临时/打算 → skip（不进长期事实）。
"""
from __future__ import annotations

import re

BOT_SELF_RE = re.compile(
    r"(我|本?(鱼|bot|助手|模型))[^。！？]{0,12}(正在?|刚才|刚刚)?[^。！？]{0,8}"
    r"(调用|尝试|执行|发送|回复|触发|拦截|冷却|记忆|工具|验证|检查)|"
    r"我(会|要|打算|准备|正在|刚刚)(去|来)?(发|回|说|做|调用|尝试|执行)"
)
TEMP_STATE_RE = re.compile(
    r"(今天|现在|此刻|这会儿|刚才|最近)?(好累|太累|好困|好饿|好渴|好烦|好开心|好难过|"
    r"很累|很困|很饿|疲惫|困了|饿了|渴了|无聊|累了|有点累|困死|累死)"
)
PLAN_RE = re.compile(r"(?:打算|计划|想要|想去|下次|以后|回头|改天).{0,8}(?:去|做|学|买|玩|写|搞|看|试试)|准备.{0,6}(?:去|做|买|玩|写|搞)(?!试)")
QUOTE_RE = re.compile(
    r"(他说|她说|他们说|有人(说|觉得|讲)|网上(说|讲)|"
    r"听(?:他|她|他们|朋友|别人|人|同事|同学|老师)说|"
    r"听说(?!唱|书|相声|评书|播客|广播|电台|音乐|歌|曲|rap|嘻哈|摇滚|脱口秀|有声)|"
    r"据(?:说|闻)|引用|扮演|假设|(?:如果|假如|要是)我是|比如说|举个例子)",
    re.IGNORECASE,
)
# 助手自述喜好不应进「他的」长期事实（her_views 另路）
ASSISTANT_CLAIM_RE = re.compile(
    r"^(助手|她|聊天伙伴|我(?:这边|自己)?)[^。]{0,8}(喜欢|讨厌|觉得|认为)"
)

ALLOW = "allow"
DENY = "deny"
SKIP = "skip"  # 非耐久：不进长期记忆


class Verdict(dict):
    @property
    def decision(self) -> str:
        return self["decision"]

    @property
    def reason(self) -> str:
        return self["reason"]


class WriteGate:
    """judge(candidate) -> Verdict
    candidate:
      text, evidence, category (preferences|facts|style),
      source_type: user_message | bot_utterance | unknown
      speaker: user | bot | unknown
    """

    def judge(self, cand: dict) -> Verdict:
        text = str(cand.get("text", "") or "")
        evidence = str(cand.get("evidence", "") or "")
        blob = text + " " + evidence
        source_type = str(cand.get("source_type", "user_message") or "user_message")
        speaker = str(cand.get("speaker", "user") or "user")

        def deny(reason: str) -> Verdict:
            return Verdict({"decision": DENY, "reason": reason})

        def skip(reason: str) -> Verdict:
            return Verdict({"decision": SKIP, "reason": reason})

        if source_type == "bot_utterance" or speaker == "bot":
            return deny("来源为助手自述，不进用户长期事实")
        if BOT_SELF_RE.search(blob) or ASSISTANT_CLAIM_RE.search(text.strip()):
            return deny("命中助手自述/工具意图特征")
        if QUOTE_RE.search(blob):
            return skip("转述/角色扮演/假设，不进长期事实")
        if TEMP_STATE_RE.search(blob):
            return skip("临时情绪/体感，不进长期事实")
        if PLAN_RE.search(blob):
            return skip("未兑现打算/计划，不进长期事实")
        if speaker not in ("user", "unknown"):
            return deny("说话主体不是用户")
        return Verdict({"decision": ALLOW, "reason": "用户显式陈述"})


GATE = WriteGate()
