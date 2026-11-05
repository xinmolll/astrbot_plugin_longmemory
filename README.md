# astrbot_plugin_longmemory
私聊长期记忆（preferences/facts/style，每条带用户原话佐证）+ 每晚定时日记。移植自自制 QQ 机器人 memory.mjs。
命令：/memory list | /memory forget <编号> | /memory clear | /memory learn | /diary read [日期] | /diary write [日期]
数据：data/plugin_data/astrbot_plugin_longmemory/

## 安装
在 AstrBot WebUI 的插件管理里选择「从仓库安装」，填入本仓库地址：

https://github.com/xinmolll/astrbot_plugin_longmemory

安装完成后重载插件或重启 AstrBot。本仓库的插件文件放在根目录，AstrBot 会直接从仓库根目录安装。

## 必填设置
打开本插件的设置，至少填写下面两项，否则主动消息和每晚日记不会发出：

- **owner_id**：主人的 QQ 号。留空时跳过主动找人聊天、短时追问，以及每晚写日记。
- **diary_session**：写日记、选择模型/人格时使用的会话 ID，格式如 `napcat:FriendMessage:你的QQ号`。留空时，若已填写 owner_id，会退回 `napcat:FriendMessage:<owner_id>`，或使用已经私聊过、保存在关系笔记里的会话；两者都没有时跳过写日记和主动发送。

日记时间、是否把写好的日记私聊发给主人、主动消息的时间窗和间隔等，可按需要再改。

v1.5.0：同一段聊天内（默认沉默 30 分钟算新一段，最长 3 小时）记忆、背景和关系笔记的注入保持不变，让 DeepSeek 等服务商的前缀缓存能命中，省 token；新记忆在下一段聊天生效。可用 ctx_refresh_idle_minutes / ctx_refresh_max_hours 调整。

v1.5.1：话题是否聊完改为他隔一会儿（followup_check_minutes，默认 1.5 分钟）没回才判断，不再每条回复都调一次模型。

## 固定背景
可以把 `about_owner.md` 放在插件目录（与 `main.py` 同级），写入不会被自动整理覆盖的固定背景。聊天注入时，这份内容会放在长期记忆前面，只对主人生效。按用户区分的背景放在数据目录 `about/<用户ID>.md`。

v1.5.2：日记改为口语叙事（不写清单/配置）；注入记忆时附固定「记忆边界」短句；主动/追问改为许可式，可输出「（不说）」跳过。

v1.5.3：减复读/穿帮——关系笔记不固化胡说；学习不把套话记入口吻；主动消息少叮嘱。

v1.5.4：表白/喜欢相关回复收软——别用「我不能说」禁令腔，也不把这类胡说固化进关系笔记；不逼回那句。
