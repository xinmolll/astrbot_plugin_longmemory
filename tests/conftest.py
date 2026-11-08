"""Lightweight AstrBot stubs so LongMemory can be imported without the real runtime."""
import sys
import types
from pathlib import Path


def _ensure_astrbot_stubs():
    if "astrbot.api" in sys.modules:
        return

    def pkg(name):
        m = types.ModuleType(name)
        m.__path__ = []
        sys.modules[name] = m
        return m

    api = pkg("astrbot.api")
    api.AstrBotConfig = dict
    api.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )

    class _CG:
        def command(self, *a, **k):
            return lambda f: f

    ev = pkg("astrbot.api.event")
    ev.AstrMessageEvent = type("AstrMessageEvent", (), {})
    ev.filter = types.SimpleNamespace(
        on_llm_request=lambda *a, **k: (lambda f: f),
        on_llm_response=lambda *a, **k: (lambda f: f),
        on_decorating_result=lambda *a, **k: (lambda f: f),
        command_group=lambda *a, **k: (lambda f: _CG()),
        command=lambda *a, **k: (lambda f: f),
    )
    ev.MessageChain = type("MessageChain", (), {"message": lambda self, t: t})

    prov = pkg("astrbot.api.provider")
    prov.LLMResponse = object
    prov.ProviderRequest = object

    star = pkg("astrbot.api.star")
    star.Context = object
    star.Star = object
    star.StarTools = types.SimpleNamespace(get_data_dir=lambda n: Path("/tmp"))
    star.register = lambda *a, **k: (lambda cls: cls)

    comp = pkg("astrbot.core.message.components")
    comp.Face = object
    comp.Plain = object
    mt = pkg("astrbot.core.platform.message_type")
    mt.MessageType = types.SimpleNamespace(FRIEND_MESSAGE="friend")
    pkg("astrbot")
    pkg("astrbot.core")
    pkg("astrbot.core.message")
    pkg("astrbot.core.platform")

    bn = types.ModuleType("baidu_netdisk")
    sys.modules["baidu_netdisk"] = bn
    sys.modules["astrbot_plugin_longmemory"] = types.ModuleType("astrbot_plugin_longmemory")
    sys.modules["astrbot_plugin_longmemory.baidu_netdisk"] = bn


_ensure_astrbot_stubs()
