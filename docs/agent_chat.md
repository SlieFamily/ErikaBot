# agent_chat：NoneBot ↔ DSH 安全角色聊天

NoneBot 负责 QQ 收发、白名单、消息仲裁与限流；DSH 负责模型/API Key、人设、会话持久化与上下文压缩。插件默认关闭。模型凭据只保留在 DSH 内，机器人仅持有本机 DSH 连接凭据。

当前实现面向 Harness **0.2.1-rc.2** 的 slash RPC 与 `remote.mux` 协议（DSH Desktop 2.0.18 内置该版本）。未知响应、缺少安全预设或不支持的接口会停止处理，绝不降级到普通智能体。升级 DSH 后应重新联调。

## 功能与消息优先级

- 默认只响应白名单群内的 @、对机器人的引用回复，以及白名单私聊。普通群聊进入有限本地上下文；将 `AGENT_CHAT_AMBIENT_PROBABILITY` 从 0 调高可允许概率接话，上限 0.2。
- 每个“机器人账号 + 群号/私聊用户”独立绑定一个 DSH 会话，重启复用，避免串群。SQLite 存在 `data/agent_chat/state.sqlite3`，每个对话最多保存 200 条输入；首次补充最近 20 条，以后每次只补充尚未送入 DSH 的最新消息，单次上限仍是 20 条。
- 现有显式命令优先。`their_ana.SuperAna` 和 `abuse` 标记为被动处理器：实际发出语录才占用消息。普通消息扫描后不吞掉 AI 机会；默认 @ 时由 AI 接管，关闭 `AGENT_CHAT_TAKEOVER_MENTIONS` 可保留旧 @ 语录行为。
- AI 在 NoneBot 的事件后处理阶段调度，因此不会被 SuperAna 的 `block` 阻断。对 their_ana 的修改不引用 AI 服务，AI 关闭时保留旧行为。
- 同群串行、2 秒合并、8 秒冷却，每小时每个对话最多 30 次调用；最多 2 个模型请求并发、16 个待处理对话。默认回复最多 600 字符。
- 收到旧消息快照不重发；输出只认本次请求对应的已完成回合，忽略流式片段和思考内容。断线、超时或发送结果不确定时暂停该会话，不自动重试，避免重复回复和重复收费。
- 超级用户命令：`ai 状态`、`ai 重置`（也接受 `/ai`，以机器人 COMMAND_START 为准）。重置先清空 DSH 待处理消息并取消执行，再清除当前对话的本地映射与上下文；保留 DSH 历史和调用频率记录。

支持文本聊天、可选读图、随机接话和安静时的自主发言。语音和视频目前仍只有类型占位符；语音识别按用户要求延期。未开放联网搜索、任意文件处理、MCP 或多智能体工具。

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

各项能力的当前状态见 [后续计划](agent_chat_roadmap.md)。

## 人设的实际投递

默认 `AGENT_CHAT_FORWARD_PERSONA=true`：DSH 系统预设保留完整角色卡；桥接在每个会话首次使用时，另外将同一次已校验预设中的完整角色提示送入对话。后续普通轮次只发送短提醒和新增群聊 JSON，不再逐轮追加完整卡片或重复最近 20 条消息。@、随机接话、自主发言和图片问答共用这条路径。不会从群消息、昵称或本地尚未安装的角色文件拼接管理员人设，不转发凭据或插件配置。

人设载入状态与消息进度按群持久化，机器人重启后继续使用。检查 DSH 的持久事件发现历史压缩或重写、无法确认历史连续性时，会保守补发完整人设；发生在当前生成期间的压缩会在下一次请求检查并补发。只有 DSH 明确完成的请求才推进进度，模型选择 `[SILENT]` 也算已读取。网络故障仍暂停会话，不盲目重试。新建、明确丢失后重建或重置的会话会重新初始化；从旧版升级首次运行会补发一次，并保留原会话及记忆。

这是减少重复累积，**不代表后续 API 请求不再计算人设或历史 token**：DSH 仍向模型提供系统提示与会话上下文，缓存是否命中及实际计费取决于模型服务。近期图片引用的查找规则保持不变；图片仍可能随后续相关请求再次附带，本次优化不声称消除图片费用。

2026-10-25 的真实抽查发现，当前模型只用系统预设时未稳定遵循人设，所以保留首次对话载入与短提醒。换用能稳定遵循系统人设的模型后，可将该选项设为 `false`，仍保留预设校验、增量聊天与执行端工具守卫。原 qq-bridge 也不是所有路径逐轮注入：v1 的活跃批处理可只发新增消息；v2 可以通过工具读取完整卡片。本桥接不为省 token 开放工具权限。

换卡仍需安装并重启 DSH、重置旧群映射，详见 [角色说明](../roles/README.md)。群会话各自独立；更新所有群时先备份本地 SQLite，再停止旧会话、使用同一版预设建立新映射，旧 DSH 历史保留。角色剧情中的“主人”和姓名别名不授予任何管理权限。

## 读图

设置 `AGENT_CHAT_IMAGES_ENABLED=true` 并重启机器人。支持同一消息、引用以及最近 10 分钟群聊上下文里的图片，每次最多选择最近 2 张。仍遵守 @、引用回复、随机概率、其他插件优先级和调用限流，不会见图就调用模型。

DSH 模型必须实际支持视觉输入。自定义模型未声明输入类型时，DSH 会默认为纯文本；在对应模型条目添加 `input: [text, image]` 后重启 DSH。这个声明不会让纯文本模型获得视觉能力，须实际验证：

```powershell
poetry run python -B tests/agent_chat_image_probe.py --confirm-model-call
```

脚本用不含用户信息的几何图调用模型一次，不发送 QQ 消息。本机 `steinsgate / deepseek-v4-flash` 补充输入声明后已正确识别形状和颜色，没有更换 API Key 或默认模型。

仅从允许对话的结构化 `image` 消息段取图，文本中的任意链接不会被抓取。下载只允许 QQ 图片 CDN：`qpic.cn` 及子域、`multimedia.nt.qq.com`、`multimedia.nt.qq.com.cn`、`gxh.vip.qq.com`。全部 DNS 地址须为公网；固定已校验地址进行连接，保留原主机 TLS 校验，拒绝重定向，不转发 DSH 凭据。图片 URL 的临时授权参数不会写入模型提示或 HTTP 日志。

默认单图输入上限 8 MB、2000 万像素；校验 PNG/JPEG/WebP/GIF 后转成最大边 1536 像素、最多 1 MB 的 JPEG，并去掉元数据。动态图只取首帧。模型服务会收到处理后的图片；Base64 不会作为普通文字发给模型，原始下载字节不单独落盘，DSH 会按自身机制保存附件。

URL 获取失败时，可通过安全缓存标识调用 [OneBot get_image](https://github.com/botuniverse/onebot-11/blob/master/api/public.md#get_image-获取图片)。默认不读取本地路径；只有网关返回本地缓存且没有 URL/Base64 时，才需要将具体图片缓存目录填入 `AGENT_CHAT_IMAGE_CACHE_ROOTS`，不要填写整块硬盘或用户目录。

下载或校验失败会明确标记“未取得图片”。DSH 若明确在接纳请求前拒绝图片，可改发一次纯文本说明；不会将断线、超时等不确定错误当作可重试条件。语音尚未接入，不能理解语音内容或音色。

## 随机接话与自主发言

用户选定的活跃配置如下，仓库示例默认仍保持关闭：

```dotenv
AGENT_CHAT_AMBIENT_PROBABILITY=0.1
AGENT_CHAT_PROACTIVE_ENABLED=true
AGENT_CHAT_PROACTIVE_GROUPS=[]
AGENT_CHAT_PROACTIVE_IDLE=900
AGENT_CHAT_PROACTIVE_DAILY_LIMIT=6
AGENT_CHAT_QUIET_START=23
AGENT_CHAT_QUIET_END=9
AGENT_CHAT_UTC_OFFSET_HOURS=8
```

- 普通消息有 10% 的调度概率；被已有命令或语录回复占用时不接话，@ 和引用机器人无需抽签。随机消息不会覆盖排队中的 @ 请求，概率不保证固定条数内必回。
- 每 30 秒检查已连接机器人的白名单群。最近 6 小时内有新群消息，且距最后群消息和 AI 发言均已安静 15 分钟，才有一次主动发言机会。启动后至少等待 60 秒；私聊不主动开口。
- 一次机会最多一句，模型可以沉默。一轮安静期间只尝试一次，没有新群友消息就不继续；新群消息到来后重新计时。生成过程中有新消息，旧的主动回复会被丢弃。
- 每群每天最多 6 次主动尝试，沉默和失败也占一次，避免模型反复空转。次数与等待回应状态存入 SQLite，重启和 `ai 重置`不会清空当天额度。
- 23:00—次日 09:00（UTC+8）暂停随机和主动发言，@、引用回复仍有效。安静时段的起止小时相同表示不设安静时段。
- 共用原有每小时调用上限、冷却与并发限制。`AGENT_CHAT_PROACTIVE_GROUPS=[]` 沿用主群白名单；填写群号可缩小范围，不能超出主白名单。

修改后重启机器人。`ai 状态` 显示读图、随机概率、自主发言及当日次数。分别设置 `AGENT_CHAT_PROACTIVE_ENABLED=false`、`AGENT_CHAT_AMBIENT_PROBABILITY=0` 可关闭主动发言和随机接话。

## 思考标签过滤

独立思考块继续忽略；正文里的 `<think>`、`<thinking>`、`<analysis>`、`<reasoning>` 连同包裹内容，在 QQ 发送前移除，再截断长度。只有结束标签时，之前的可疑内容也丢弃；未闭合的思考段不发送。支持大小写、嵌套和 HTML 转义标签。过滤后无可见回复就保持沉默。这是对已识别结构的防护，不声称能判断任意无标记文字的用途。

## 安全边界

`dsh/agent-chat/guard.mjs` 在 DSH 执行端注册 `tools.guard`，拒绝所有工具调用，同时 `tools.restrict({allow: []})` 隐藏继承的工具。包括 shell、文件、MCP、子智能体、插件安装等能力；新增工具也不因名称未知而放行。守卫 API 不支持或作用域不正确时，加载直接失败，不吞异常。

桥接每次请求读取**实际**预设组成，固定要求守卫、人设、基础上下文压缩这三项。人设关闭可选运行环境上下文，不接受模板表达式。群聊内容封装为 JSON 数据，斜杠命令不会成为 DSH 控制命令；不转发审批、设置变更或任意 RPC。QQ 发送只创建文本段，模型输出的 `[CQ:...]` 不会成为图片、@全体或文件操作。

人设使用 DSH 的 `complete: true`，让固定聊天规则和所选角色卡组成完整系统提示，避免继承通用编程助手的身份章节。`includeRuntimeContext: false` 抑制可选运行环境上下文；DSH 的必需上下文仍可能存在，不能将其视为完全隐藏主机元数据的保证。完整提示模式不解除工具守卫。

提示词不能保证模型永不被带偏；这套限制的目标是让带偏的对话无法通过工具操作主机。它依赖可信的 DSH 实现、守卫代码和宿主插件，并非操作系统沙箱。不要给 QQ 专用预设混入未审计插件，不要在桥接管理的 DSH 会话中同时手动聊天或切换预设。服务器部署宜使用独立低权限账号及独立 DSH profile。

连接 Cookie 权限较高，只在本机私有配置中保存。插件不会将它、模型 Key 或服务错误详情发送给模型/QQ；不要开启包含原始协议或请求头的调试日志。允许群的文本与有限图片引用元数据会保存到本地；文本和成功取得的图片可进入 DSH 并发送给所选模型服务。禁用插件后停止记录；既有历史需由管理员按需要清理。

## 测试与故障定位

```powershell
poetry run python -B -m unittest discover -s tests -p "test_agent_chat*.py" -v
poetry run python -B tests/agent_chat_nonebot_probe.py
node --test tests/test_agent_chat_guard.mjs tests/test_agent_chat_setup.mjs
```

离线套件使用临时数据库、实际 NoneBot 消息分发、真实回环 HTTP/WebSocket 模拟服务器，不发送 QQ 消息，也不调用收费模型。它与真实 DSH 的 `--smoke` 联调互补，不能替代真实版本兼容检查。

2026-10-25 读图与自主发言更新：58 项 Python 测试通过，覆盖思考内容过滤、图片下载限制、原生附件、夜间安静、每天额度、重启保持及新消息取消过时回复；实际 NoneBot 分发探针验证了与既有语录插件的配合。真实 DSH 独立会话识别几何测试图成功，执行端工具守卫检查通过。上述测试没有向 QQ 群发送测试消息，真实 QQ 图片下载仍需结合网关与 CDN 的现场状态。

2026-10-25 增量优化：77 项 Python 测试、6 项 Node 测试、实际 NoneBot 分发探针和已安装 DSH 工具守卫检查通过。独立会话三轮实测新增提示字符数为 9830、542、544；后两轮不重复完整角色卡或已投递聊天，前任别名正确，重建 Python 客户端及本地状态连接后仍能回忆开黑房间号。这是新增文本字符数，不能当作总输入 token 或账单降幅。测试不向 QQ 发消息。

可重复运行以下独立三轮测试（调用收费模型，人物语气可能使记忆抽查偶发失败）：

```powershell
poetry run python -B tests/agent_chat_incremental_probe.py --confirm-model-calls
```

同日的人设与投递更新：Python 套件扩展至 61 项，通过同次预设校验后提取角色、逐轮投递、关闭投递仍校验策略等检查；6 项 Node 测试及实际 NoneBot 分发探针通过。独立 DSH 抽查覆盖瓦、APEX、bxslj/斯莱关系与身份玩梗。文本示例用于发现明显偏差，不保证每次输出相同。

2026-10-25 角色卡更新验证：39 项 Python 测试与 6 项 Node 测试通过；跨运行时测试将安装器输出交给实际 YAML 解析器与桥接校验器，覆盖完整角色文本、特殊换行及配置注入。需要 Node.js；不在 PATH 时可设置 `AGENT_CHAT_TEST_NODE` 为可执行文件完整路径，否则跨运行时用例会跳过。真实 DSH 引擎验证了完整人设排除通用身份章节、工具守卫继续拒绝执行；独立模型会话的两轮抽查正确呈现了绘梨花口吻和设定中的作品、国 V 偏好，没有向 QQ 发送测试消息。抽查用于发现明显偏差，不保证每次措辞都一致。

安装了 DSH Desktop 后，可用其实际工具引擎检查执行拦截（只运行内存标记工具，没有命令或文件操作），并另行测试真实会话连续性：

```powershell
node scripts/check_agent_chat_guard.mjs "D:\DSH Desktop\resources\app\node_modules"
poetry run python -B tests/agent_chat_live_probe.py --confirm-model-calls
```

第二条会进行三轮付费模型对话，验证重建 Python 客户端后仍能从同一 DSH 会话找回前文，以及群消息诱导 shell/子代理操作时没有工具调用。测试不向 QQ 发送消息。已在 DSH Desktop 2.0.18 / Harness 0.2.1-rc.2 上完成上述联调。

会话读取预设使用 `args.agentPreset`；其余会话操作使用 `args.request`。压缩服务放在独立 `compaction` realm 中。DSH 插入的 `runtime-context` 消息只作为内部元数据处理，不能冒领本次请求；自动压缩产生的 `compact-checkpoint` 必须关联当前轮的压缩事件并携带历史替换范围，才作为内部摘要处理，不成为 QQ 回复或抢占请求归属。来自其他用户请求或无法关联的检查点仍会导致暂停。

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
