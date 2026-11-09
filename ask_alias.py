"""问法别名：规则归一 + 轻量别名生成/匹配。"""
from __future__ import annotations

import json
import re

# 口语 → 检索用概念词（便宜、零 LLM）
QUERY_NORMALIZE = [
    (re.compile(r"多大了|几岁|年龄|芳龄"), ["年龄", "岁", "生日"]),
    (re.compile(r"叫什么|名字|怎么称呼|喊你|叫你"), ["叫", "名字", "称呼"]),
    (re.compile(r"住哪|哪里人|老家|家乡"), ["住", "老家", "家乡", "哪里"]),
    (re.compile(r"喜欢吃|爱吃|口味|吃啥"), ["喜欢吃", "爱吃", "口味"]),
    (re.compile(r"不喜欢|讨厌|雷点|别提"), ["不喜欢", "讨厌", "雷"]),
    (re.compile(r"上班|工作|做什么的|职业"), ["工作", "上班", "职业"]),
    (re.compile(r"学校|读书|考试|专升本|学习"), ["专升本", "考试", "学习", "图书馆"]),
    (re.compile(r"吃药|失眠|ADHD|注意缺陷|健康"), ["ADHD", "药", "安眠", "健康"]),
    (re.compile(r"爱好|喜欢干|平时.*玩"), ["爱好", "喜欢", "兴趣"]),
]

ALIAS_PROMPT = (
    "你是记忆检索助手。给若干条关于用户的记忆事实，"
    "为每条生成最多3个「用户提起这件事时最可能说的短句」。"
    "要求口语短句、换种说法、不要照抄原文。"
    "只输出JSON数组：[{\"text\":原事实原文, \"ask\":[\"问法1\",\"问法2\"]}]，不要其他文字。"
)


def expand_query(query: str) -> list[str]:
    """把口语问法扩成关键词列表（含原文碎片）。"""
    q = str(query or "").strip()
    out = []
    if q:
        out.append(q)
        # 粗切
        for part in re.split(r"[\s，。？！?!,.]+", q):
            if len(part) >= 2:
                out.append(part)
    for cre, concepts in QUERY_NORMALIZE:
        if cre.search(q):
            out.extend(concepts)
    # 去重保序
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def rule_aliases_for_text(text: str) -> list[str]:
    """无 LLM 时的兜底别名。"""
    t = str(text or "")
    asks = []
    pairs = [
        (r"岁|年龄|生日", ["多大了", "几岁了", "年龄"]),
        (r"叫|名字|称呼|信", ["叫什么", "怎么叫你", "名字"]),
        (r"专升本|考试|3\s*月\s*28|图书馆", ["考试什么时候", "还在备考吗", "去图书馆吗"]),
        (r"ADHD|注意缺陷|安眠|布洛芬|吃药", ["身体怎么样", "还吃药吗", "睡眠怎么样"]),
        (r"喜欢吃|爱吃", ["喜欢吃什么", "口味怎么样"]),
        (r"不喜欢|讨厌|雷", ["有什么雷点", "不喜欢什么"]),
        (r"工作|上班", ["做什么工作", "还在上班吗"]),
    ]
    for pat, als in pairs:
        if re.search(pat, t):
            asks.extend(als)
    # 去重
    seen, out = set(), []
    for a in asks:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:4]


def match_score(query: str, text: str, aliases: list | None = None) -> float:
    """便宜 2-gram / 子串匹配分。"""
    q = str(query or "").strip()
    keys = expand_query(q)
    blob = str(text or "")
    als = [str(a) for a in (aliases or []) if a]
    hay = blob + " " + " ".join(als)
    if not q or not hay:
        return 0.0
    score = 0.0
    # 问法别名与用户原问直接互为子串
    for a in als:
        if len(a) >= 2 and (a in q or q in a):
            score += 2.5
    for k in keys:
        if len(k) >= 2 and k in hay:
            score += 2.0 if (k in als or k in blob) else 1.0
        if len(k) >= 4:
            for i in range(len(k) - 1):
                bg = k[i : i + 2]
                if bg in hay:
                    score += 0.15
    return score


def parse_alias_json(raw: str) -> dict[str, list[str]]:
    text = str(raw or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("[")
    if start < 0:
        return {}
    body = text[start:].replace("，", ",").replace("：", ":")
    data = None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        last = body.rfind("}")
        if last < 0:
            return {}
        body2 = body[: last + 1].rstrip(",")
        opens = body2.count("{") - body2.count("}")
        body2 = body2 + "}" * max(0, opens) + "]"
        try:
            data = json.loads(body2)
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, list[str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("text") or item.get("id") or "").strip()
        asks = item.get("ask") or item.get("aliases") or []
        if not key or not isinstance(asks, list):
            continue
        cleaned = []
        for a in asks:
            s = re.sub(r"\s+", "", str(a or ""))
            if len(s) >= 2:
                cleaned.append(s)
        if cleaned:
            out[key] = cleaned[:4]
    return out


def build_alias_user_prompt(items: list[dict]) -> str:
    lines = []
    for it in items:
        t = str(it.get("text") or "").replace("\n", " ")[:80]
        if t:
            lines.append(f"- {t}")
    return "记忆事实：\n" + "\n".join(lines)
