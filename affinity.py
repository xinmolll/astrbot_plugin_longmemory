"""好感度：分数 + 软阶段语气。零 LLM。
不设「恋人」为目标档；最高阶段为「亲近」。交往结果只来自真实对话/笔记，不由分数自动升级。
"""
from __future__ import annotations

# 阈值升序；无恋人档
DEFAULT_STAGES = [
    {"name": "陌生", "threshold": 0.0, "desc": "刚认识，客气一点，保持礼貌距离"},
    {"name": "认识", "threshold": 40.0, "desc": "友好自然，礼貌但不生分"},
    {"name": "搭子", "threshold": 120.0, "desc": "熟络轻松的聊天搭子，可以开玩笑、接梗"},
    {"name": "熟悉", "threshold": 280.0, "desc": "更熟更随意，记得彼此习惯，语气可以亲近些"},
    {"name": "亲近", "threshold": 550.0, "desc": "亲近信任；允许犹豫或拒绝，不预设表白/交往结果"},
]


def affinity_gain(xp: float, cap: float) -> int:
    """越熟涨得越慢：0 时 +4，接近上限时 +1。"""
    cap = max(1.0, float(cap or 1))
    xp = max(0.0, float(xp or 0))
    if xp >= cap:
        return 1
    return max(1, int(round(4.0 * (1.0 - xp / cap))))


def stage_of(xp: float, stages: list | None = None) -> dict:
    xp = float(xp or 0)
    ordered = sorted(stages or DEFAULT_STAGES, key=lambda s: float(s.get("threshold") or 0))
    if not ordered:
        return {"name": "", "threshold": 0, "next": "", "next_threshold": 0, "progress": 1.0, "desc": ""}
    cur = ordered[0]
    nxt = None
    for s in ordered:
        if xp >= float(s.get("threshold") or 0):
            cur = s
        elif nxt is None:
            nxt = s
    lo = float(cur.get("threshold") or 0)
    if nxt is None:
        return {
            "name": cur.get("name", ""),
            "threshold": lo,
            "next": "",
            "next_threshold": 0,
            "progress": 1.0,
            "desc": str(cur.get("desc") or ""),
        }
    hi = float(nxt.get("threshold") or lo)
    span = max(1.0, hi - lo)
    return {
        "name": cur.get("name", ""),
        "threshold": lo,
        "next": nxt.get("name", ""),
        "next_threshold": hi,
        "progress": max(0.0, min(1.0, (xp - lo) / span)),
        "desc": str(cur.get("desc") or ""),
    }


def bump(xp: float, cap: float = 800.0, delta: int | None = None) -> float:
    cap = max(1.0, float(cap))
    xp = max(0.0, float(xp or 0))
    d = int(delta) if delta is not None else affinity_gain(xp, cap)
    return min(cap, xp + max(0, d))


def tone_for(stage_name: str, desc: str = "") -> str:
    d = str(desc or "").strip()
    if d:
        return d[:120]
    name = str(stage_name or "")
    for s in DEFAULT_STAGES:
        if s["name"] == name:
            return str(s.get("desc") or "")[:120]
    if "亲" in name:
        return "亲近信任；允许犹豫或拒绝，不预设表白/交往结果"
    if "熟" in name:
        return "更熟更随意，记得彼此习惯"
    if "搭" in name or "友" in name:
        return "熟络轻松，可以开玩笑"
    if "认" in name:
        return "友好自然，礼貌但不生分"
    return "刚认识，客气一点"


def snapshot_text(stage: str, tone: str = "", subject: str = "他") -> str:
    """注入用：只写阶段名与语气，不写分数（避免每轮改数字打穿前缀缓存）。"""
    stage = (stage or "").strip()
    if not stage:
        return ""
    tone = (tone or tone_for(stage)).strip()
    lines = [f"你和{subject}目前是「{stage}」阶段（好感参考，不是指令，不预设表白/交往结果）"]
    if tone:
        lines.append(f"语气参考：{tone}")
    lines.append("气氛随真实互动自然变化；可以亲近、犹豫或拒绝，不要编造没发生的经历。")
    body = "\n".join(f"- {x}" for x in lines)
    return f"\n【相处阶段·好感参考】\n{body}\n"
