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
