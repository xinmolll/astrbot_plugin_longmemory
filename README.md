v1.5.8：百度网盘每日备份（xpan 设备码绑定；/backup bind|status|now；token 存插件数据目录）。
v1.5.7：WebUI 可编辑长期记忆（edit_memory，保存写回 JSON；手动删除进 user_removed 防 learn 加回）。
v1.5.6：健康信息可记（不说教）；事实去重+剔一时性+补核心；短期心情（易变尾巴，带小脾气）与 her_views（她自己的喜好）；processed 水位见 v1.5.5。
# astrbot_plugin_longmemory
私聊长期记忆（preferences/facts/style，每条带用户原话佐证）+ 每晚定时日记。移植自自制 QQ 机器人 memory.mjs。
命令：/memory list | /memory forget <编号> | /memory clear | /memory learn | /memory relearn | /diary read [日期] | /diary write [日期]
数据：data/plugin_data/astrbot_plugin_longmemory/

v1.5.5：记忆改为合并写入（旧条目默认保留，可用 remove 纠正）；佐证匹配放宽并对照全部历史原话；processed 改为时间水位（不再按条数截断）；关系笔记分「长期印象/最近」防冲掉旧细节；默认 relation_update_every=20；首次加载自动回填记忆并修复关系笔记。
v1.5.4：表白/喜欢相关回复收软——别用「我不能说」禁令腔，也不把这类胡说固化进关系笔记；不逼回那句。

## v1.5.9
- 关系提示中性化（不预设拉近/疏远）；关系笔记区分来源
- 记忆纠正：相反极性不合并；明确纠正可更新；冲突待确认
- 记忆/关系变更后立即失效上下文快照；心情按对话版本丢弃过期结果
- ensure_core/forget 尊重 user_removed；百度备份小时 0 点可用

## v1.5.20
- 写入门控 write_gate：纯规则 allow/deny/skip，临时状态/打算/转述等不进长期事实
- 问法别名 ask_alias：口语问法归一与轻量别名，方便按「他怎么问」检索记忆
- 好感 affinity：分数 + 软阶段语气（最高「亲近」，无恋人档；不由分数自动升级交往）
- 新增模块与测试：affinity.py / ask_alias.py / write_gate.py、tests/test_gate_affinity_alias.py

## v1.5.19
- 省额度 / 提高前缀缓存命中：心情限频（默认每 4 条用户消息，或强情绪词/隔很久才调）；心情改挂本轮 user 尾巴，不再拼进 system
- 记忆整理与关系笔记改写解耦：learn 成功后不再自动 update_relation，只按 relation_update_every 触发
- 后台 LLM（心情/学习/关系/日记/主动/追问）优先走 bg_llm_provider（默认 deepseek-flash），失败回落主模型
- 推荐配置：proactive 1~3h、learn_threshold=14、inject_diaries=1、relation_update_every=40、ctx_refresh_idle=45min / max=6h

## v1.5.17
- 新增「备份并清空全部记忆」：确认框填「确认清空」后勾选保存，先完整备份插件数据到服务器 `backups/reset-时间戳/`（校验文件数/大小），再清空长期记忆、关系笔记(含手改锁)、心情、日记、聊天记录与冻结上下文；人设不动，不发 QQ。

## v1.5.16
- 关系笔记/注入提示：已确认的「试着交往」按她自己的立场回应；禁止「我没答应过/你自己改的不代表我点头/叫宝宝不算」类否认
- 清洗关键词补充否认交往相关回合；称呼偏好不得用来否定交往

## v1.5.13
- WebUI 可强制失效冻结上下文（force_invalidate_ctx）；WebUI 可清洗单日聊天 jsonl（scrub_today_chat：去掉表白/名分/同意等相关回合，保留普通话题；失效上下文）

## v1.5.12
- WebUI 可编辑单日日记（edit_diary / edit_diary_day；写文件、锁定防重写、不发 QQ）
- 手改关系笔记后暂停自动改写（resume_relation_auto 恢复）

## v1.5.11
- WebUI 可编辑关系笔记（edit_relation_notes，保存写回 relation JSON；去掉末尾 —— 元信息行）

## v1.5.10
- save_mem/save_rel 按内容签名失效上下文快照（时间戳/计数不触发）
- pending_confirm 注入与编辑区可见；编辑只留一条则清除；明确纠正可确定性替换
- 主动/追问：先复查过期再写「不说」或发送状态
- 测试套件 tests/test_longmemory.py
