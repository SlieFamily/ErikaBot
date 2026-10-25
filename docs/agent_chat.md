# agent_chat：NoneBot ↔ DSH 安全角色聊天

NoneBot 负责 QQ 收发、白名单、消息仲裁与限流；DSH 负责模型/API Key、人设、会话持久化与上下文压缩。插件默认关闭。模型凭据只保留在 DSH 内，机器人仅持有本机 DSH 连接凭据。

当前实现面向 Harness **0.2.1-rc.2** 的 slash RPC 与 `remote.mux` 协议（DSH Desktop 2.0.18 内置该版本）。未知响应、缺少安全预设或不支持的接口会停止处理，绝不降级到普通智能体。升级 DSH 后应重新联调。

## 功能与消息优先级

- 默认只响应白名单群内的 @、对机器人的引用回复，以及白名单私聊。普通群聊进入有限本地上下文；将 `AGENT_CHAT_AMBIENT_PROBABILITY` 从 0 调高可允许概率接话，上限 0.2。
- 每个“机器人账号 + 群号/私聊用户”独立绑定一个 DSH 会话，重启复用，避免串群。SQLite 存在 `data/agent_chat/state.sqlite3`，每个对话最多保存 200 条输入，通常向 DSH 补充最近 20 条。
- 现有显式命令优先。`their_ana.SuperAna` 和 `abuse` 标记为被动处理器：实际发出语录才占用消息。普通消息扫描后不吞掉 AI 机会；默认 @ 时由 AI 接管，关闭 `AGENT_CHAT_TAKEOVER_MENTIONS` 可保留旧 @ 语录行为。
- AI 在 NoneBot 的事件后处理阶段调度，因此不会被 SuperAna 的 `block` 阻断。对 their_ana 的修改不引用 AI 服务，AI 关闭时保留旧行为。
- 同群串行、2 秒合并、8 秒冷却，每小时每个对话最多 30 次调用；最多 2 个模型请求并发、16 个待处理对话。默认回复最多 600 字符。
- 收到旧消息快照不重发；输出只认本次请求对应的已完成回合，忽略流式片段和思考内容。断线、超时或发送结果不确定时暂停该会话，不自动重试，避免重复回复和重复收费。
- 超级用户命令：`ai 状态`、`ai 重置`（也接受 `/ai`，以机器人 COMMAND_START 为准）。重置先清空 DSH 待处理消息并取消执行，再清除当前对话的本地映射与上下文；保留 DSH 历史和调用频率记录。

这是文本角色聊天桥接。图片、语音、视频仅转成类型占位符，不下载媒体。没有移植 qq-bridge 的 MCP 主动发消息、联网搜索、文件处理或复杂多智能体功能。

## 配置与安装

1. 在 DSH 配置模型并确认普通聊天成功。Desktop 使用兼容模式，开启“浏览器访问”，网络范围保持“仅本机”。普通 HTTP 请求返回 403 时应先检查这一设置。不要提取或伪造桌面内部 renderer capability 来绕过它。
2. 将专用预设安装到**运行中的那个 profile**。例如 Windows Desktop 的 profile 通常是 `$HOME/.dsh/profiles/desktop`；服务器 Web profile 通常是 `~/.dsh/profiles/web`。先预览，再应用：

   ```powershell
   node scripts/setup_agent_chat_dsh.mjs --profile "$HOME/.dsh/profiles/desktop"
   node scripts/setup_agent_chat_dsh.mjs --profile "$HOME/.dsh/profiles/desktop" --apply
   ```

   安装器保留已有依赖及 bundles，备份 package.json，并将守卫与预设复制到 profile 下按内容哈希命名的目录，再创建模块链接。切换 Git 分支不会改变已部署守卫。不会安装网络依赖、启动进程、删除历史或修改模型配置。应用后重启 DSH；若 profile 管理器要求安装依赖，按该版本 DSH 的插件安装流程操作。

3. 在项目根目录创建私有配置：

   ```powershell
   Copy-Item .env.agent_chat.example .env.agent_chat
   ```

   填写准确的 `AGENT_CHAT_DSH_URL`（Desktop 当前监听端口可能不是 3080）、白名单群号、DSH 登录链接里的 token 或有效的 `dsh-auth-*` Cookie。两种连接凭据选一种。不要把 LLM API Key 当作 DSH 登录 token。不要将凭据写入本仓库已跟踪的 `.env.prod`，也不要粘贴到群内。

   插件自动读取 `.env.agent_chat`；优先级为进程环境变量 > 此私有文件 > NoneBot 配置 > 默认值。私有文件禁止 `${...}` 插值，防止意外改变凭据。`AGENT_CHAT_PROVIDER` / `AGENT_CHAT_MODEL` 同时留空则使用 DSH 默认模型，也可成对填写以固定模型。

   远程服务器通过 SSH 本地转发接入，例如 `ssh -N -L 3080:127.0.0.1:3080 user@server`，插件 URL 仍使用 `http://127.0.0.1:3080`。插件仅允许字面量回环地址，HTTP 和 WebSocket 均拒绝重定向，不向任意域名转发凭据。

4. 检查真实 DSH：

   ```powershell
   poetry run python scripts/check_agent_chat.py
   poetry run python scripts/check_agent_chat.py --smoke
   ```

   第一条只校验认证与实际预设组成；第二条新建独立 DSH 会话，调用模型一次（产生费用），确认请求与回包对应并清理待执行任务。不会给 QQ 发消息，也不会改已有会话。该诊断会话的历史保留在 DSH。

5. 确认通过后设 `AGENT_CHAT_ENABLED=true`，保留明确白名单，然后 `poetry run nb run`。修改配置后重启机器人。默认人设位于 [roles/古户绘梨花.md](../roles/古户绘梨花.md)，安装器会将其作为纯文本嵌入安全预设；也可用 `--role "roles/我的角色.md"` 选择其他文件。修改人设后重新安装并重启 DSH，旧映射会要求 `ai 重置`。完整的换卡、回退和群配置步骤见 [角色设置说明](../roles/README.md)。

联网搜索、等待新消息、自主发言、图像与音频识别列入 [下一阶段计划](agent_chat_roadmap.md)，本次未实现或开启。

## 安全边界

`dsh/agent-chat/guard.mjs` 在 DSH 执行端注册 `tools.guard`，拒绝所有工具调用，同时 `tools.restrict({allow: []})` 隐藏继承的工具。包括 shell、文件、MCP、子智能体、插件安装等能力；新增工具也不因名称未知而放行。守卫 API 不支持或作用域不正确时，加载直接失败，不吞异常。

桥接每次请求读取**实际**预设组成，固定要求守卫、人设、基础上下文压缩这三项。人设关闭可选运行环境上下文，不接受模板表达式。群聊内容封装为 JSON 数据，斜杠命令不会成为 DSH 控制命令；不转发审批、设置变更或任意 RPC。QQ 发送只创建文本段，模型输出的 `[CQ:...]` 不会成为图片、@全体或文件操作。

人设使用 DSH 的 `complete: true`，让固定聊天规则和所选角色卡组成完整系统提示，避免继承通用编程助手的身份章节。`includeRuntimeContext: false` 抑制可选运行环境上下文；DSH 的必需上下文仍可能存在，不能将其视为完全隐藏主机元数据的保证。完整提示模式不解除工具守卫。

提示词不能保证模型永不被带偏；这套限制的目标是让带偏的对话无法通过工具操作主机。它依赖可信的 DSH 实现、守卫代码和宿主插件，并非操作系统沙箱。不要给 QQ 专用预设混入未审计插件，不要在桥接管理的 DSH 会话中同时手动聊天或切换预设。服务器部署宜使用独立低权限账号及独立 DSH profile。

连接 Cookie 权限较高，只在本机私有配置中保存。插件不会将它、模型 Key 或服务错误详情发送给模型/QQ；不要开启包含原始协议或请求头的调试日志。允许群的文本会保存到本地及 DSH，并送给所选模型服务。禁用插件后停止记录；既有历史需由管理员按需要清理。

## 测试与故障定位

```powershell
poetry run python -B -m unittest discover -s tests -p "test_agent_chat*.py" -v
poetry run python -B tests/agent_chat_nonebot_probe.py
node --test tests/test_agent_chat_guard.mjs tests/test_agent_chat_setup.mjs
```

离线套件使用临时数据库、实际 NoneBot 消息分发、真实回环 HTTP/WebSocket 模拟服务器，不发送 QQ 消息，也不调用收费模型。它与真实 DSH 的 `--smoke` 联调互补，不能替代真实版本兼容检查。

2026-10-25 角色卡更新验证：39 项 Python 测试与 6 项 Node 测试通过；跨运行时测试将安装器输出交给实际 YAML 解析器与桥接校验器，覆盖完整角色文本、特殊换行及配置注入。需要 Node.js；不在 PATH 时可设置 `AGENT_CHAT_TEST_NODE` 为可执行文件完整路径，否则跨运行时用例会跳过。真实 DSH 引擎验证了完整人设排除通用身份章节、工具守卫继续拒绝执行；独立模型会话的两轮抽查正确呈现了绘梨花口吻和设定中的作品、国 V 偏好，没有向 QQ 发送测试消息。抽查用于发现明显偏差，不保证每次措辞都一致。

安装了 DSH Desktop 后，可用其实际工具引擎检查执行拦截（只运行内存标记工具，没有命令或文件操作），并另行测试真实会话连续性：

```powershell
node scripts/check_agent_chat_guard.mjs "D:\DSH Desktop\resources\app\node_modules"
poetry run python -B tests/agent_chat_live_probe.py --confirm-model-calls
```

第二条会进行三轮付费模型对话，验证重建 Python 客户端后仍能从同一 DSH 会话找回前文，以及群消息诱导 shell/子代理操作时没有工具调用。测试不向 QQ 发送消息。已在 DSH Desktop 2.0.18 / Harness 0.2.1-rc.2 上完成上述联调。

会话读取预设使用 `args.agentPreset`；其余会话操作使用 `args.request`。压缩服务放在独立 `compaction` realm 中。DSH 插入的 `runtime-context` 消息只作为内部元数据处理，不能冒领本次请求；来自其他用户请求的消息仍会导致暂停。

本机初次配置使用了仅当前 Windows 用户与 SYSTEM 可读写的 `.env.agent_chat`，连接 Cookie 有效期 30 天。过期后在本机刷新配置并重启机器人；插件不会自行读取 DSH 签名密钥或扩大凭据权限。

| 诊断代码 | 处理方式 |
| --- | --- |
| `safe_preset_missing` / `unsafe_preset_composition` | 检查是否装在当前 profile、是否重启、是否被额外插件改变 |
| `dsh_auth_failed` / `dsh_auth_expired` | 刷新私有配置的 DSH 凭据并重启机器人 |
| `dsh_http_error` | 检查端口、Desktop 浏览器访问设置及 DSH 状态 |
| `dsh_ws_redirect_rejected` | 使用真实回环监听地址，不使用重定向代理 |
| `session_suspended` / `dsh_turn_timeout` | 检查 DSH 运行情况，确保旧任务停止，再执行 `ai 重置` |
| `preset_changed_reset_required` | 核查预设、地址和模型变更，再重置该对话 |
| `unexpected_tool_call` | 暂停使用，核查 DSH 守卫是否正确加载，不要放宽限制 |

不自动重发结果不确定的请求。若 DSH 清理失败，重置也会失败并保留映射；先处理 DSH 后重试。`AGENT_CHAT_ENABLED=false` 并重启机器人可立即停用本插件。

协议和守卫机制参考 [qq-bridge](https://github.com/Derpyu520/qq-bridge) 及 DSH 源码；MIT 许可见 `third_party/qq-bridge-LICENSE`。
