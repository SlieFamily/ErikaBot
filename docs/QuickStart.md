# 快速部署 Bot

## 环境依赖

本项目使用 Python、Poetry 和 [NoneBot2](https://v2.nonebot.dev)。当前 QQ 登录与消息网关为 [SnowLuma](https://github.com/SnowLuma/SnowLuma)，通过 NoneBot OneBot v11 适配器连接；历史部署使用过 NapCat。`agent_chat` 是可选插件，启用后由 DSH 管理模型 API、角色会话和受限工具。

### QQ 网关

安装并登录机器人 QQ，在网关中启用 OneBot v11 反向 WebSocket，连接机器人监听地址：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

这是 **NoneBot 的地址**，不是 DSH 模型服务地址。网关端的访问令牌与 NoneBot 的 `ONEBOT_ACCESS_TOKEN` 保持一致；端口以实际配置为准。不同网关的设置界面不同，不要照搬旧 NapCat 启动文件名。消息贴表情、戳一戳、合并转发等扩展还要求网关支持相应 OneBot API。

### 安装机器人

1. 克隆本项目，进入项目根目录，安装 Poetry。
2. 使用项目支持的 Python 版本创建环境，执行 `poetry install`；依赖和版本约束见 [pyproject.toml](../pyproject.toml) 与锁文件。
3. 核对 `.env` 指定的环境及 `.env.prod` 中的地址、端口、`SUPERUSERS`、`COMMAND_START` 和 `ONEBOT_ACCESS_TOKEN`。超级用户填写实际 QQ 号，普通群主/管理员不会自动取得 AI 管理权限。
4. `.env.prod` 已被 Git 跟踪，真实令牌不要提交或推送；DSH 凭据与 AI 开关统一放入被忽略的 `.env.agent_chat`，模型 API Key 只在 DSH 配置。

## 手动启动与停止

先启动 QQ 网关并登录；启用了 AI 时，再启动使用原 profile 的 DSH。然后在 CMD 中执行：

```bat
cd /d E:\rerika\ErikaBot
poetry run nb run
```

其他安装位置请替换目录。PowerShell 使用 `Set-Location 'E:\rerika\ErikaBot'`，随后同样执行 `poetry run nb run`；无需另开 `poetry shell`。

看到插件加载、服务启动和 OneBot 连接成功后即可使用。不要同时开两个机器人争用同一端口。手动在前台启动时，在该窗口按 Ctrl+C 停止；后台运行时先按[进程查询说明](agent_chat.md#运行进程与日志)核对所属进程，不要结束所有 `python.exe`。DSH、SnowLuma、QQ 客户端与 NoneBot 是独立进程。

普通前台启动的日志在该终端显示，不会自动保存成文件。查看既有后台日志或将今后日志重定向到文件，见[运行进程与日志](agent_chat.md#运行进程与日志)。

## 可选：启用 DSH 角色聊天

基础机器人成功连接 QQ 网关后，再按 [agent_chat 安装说明](agent_chat.md#配置与安装)配置 DSH 模型、仅本机访问、专用安全预设和私有 `.env.agent_chat`。适配版本是 DSH Desktop 2.0.18 / Harness 0.2.1-rc.2；升级后重新核验协议和预设。

默认人设是 [古户绘梨花](../roles/古户绘梨花.md)。先复制 [.env.agent_chat.example](../.env.agent_chat.example)，再填写白名单与连接配置，按需启用读图、随机接话、观察和主动发言。每群有独立持久会话，人设首次载入、普通轮次增量发送；按 QQ 号认主人使用 `AGENT_CHAT_OWNER_IDS`，命令权限仍由 `SUPERUSERS` 控制。换卡和追加群见[角色设置](../roles/README.md)。

- 联网搜索使用 DSH 的 AnySearch，AI 自主决定是否搜索并整理结果；不需要部署 Python 搜索后端。见 [AnySearch 配置](agent_chat.md#ai-自主联网搜索anysearch)。
- 轻量记忆与黑话学习还需安装本机工具回调。默认关闭，启用后后台整理另计模型用量。见[记忆与黑话配置](agent_chat.md#轻量长期记忆与黑话学习)。
- 当前本机的90轮/小时、随机2%、观察60秒等设置不是仓库默认值。完整对照及中文配置入口见[配置说明](agent_chat.md#当前部署节奏与仓库默认值)。

## 日常修改与恢复

| 要做的事 | 操作 |
| --- | --- |
| 新增群、改概率/额度、按 QQ 号认主人 | 修改 `.env.agent_chat`，等当前任务结束后重启 NoneBot；不需重置会话 |
| 更换 API Key 或批量切换模型 | 按[模型维护说明](agent_chat.md#更换-apikey-或模型)操作 DSH；改默认模型不会自动切换既有群与学习会话 |
| 会话暂停、手动输入冲突或旧回复不确定 | 先修复 DSH/API，再由超级用户在 QQ 当前群执行 `ai 恢复`；保留历史、跳过旧回复，未答问题重新提问 |
| 明确需要新的对话上下文 | `ai 重置`；下次建立新 DSH 会话，独立轻量记忆和词库仍保留 |
| 修改角色或安全预设 | 重新安装预设，正式切换时重启 DSH 并核对旧映射；保存 Markdown 不会热更新 |
| 黑话合并转发没有送达回执 | 先核对群里是否已有卡片，避免重复发送；这不等同于 DSH 会话故障，不要因此清空记忆 |

开发测试期间保持生产机器人、DSH 和 QQ 网关在线。文档修改不需重启；代码在隔离副本验证通过后才正式部署。完整流程见[在线测试与部署](agent_chat.md#保持-qq-在线的测试与部署)。
