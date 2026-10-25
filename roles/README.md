# agent_chat 角色卡与设置

默认角色卡是 [古户绘梨花.md](古户绘梨花.md)。修改它即可调整性格、口吻、爱好、背景和对话示例。文件使用 UTF-8 编码；无须再把整个人设写进 YAML。

## 文件分别负责什么

| 文件 | 作用 |
| --- | --- |
| `roles/古户绘梨花.md` | 完整人设，可直接编辑或复制成另一个角色 |
| `dsh/agent-chat/preset.patch.yml` | 固定聊天协议、权限边界和角色插入位置；通常不用改 |
| `dsh/agent-chat/guard.mjs` | DSH 执行端工具拦截，角色卡不能解除 |
| `.env.agent_chat` | 本机连接凭据、群白名单、回复概率等私有配置 |
| `scripts/setup_agent_chat_dsh.mjs` | 读取角色卡，生成并安装预设的固定版本 |

预设使用 DSH 的完整提示模式（`complete: true`），避免通用编程助手的身份章节混入角色表达。机器人仍明确知道自己是在扮演虚构角色；承认机器人身份不需要否认角色的既定喜好。

安装器只读取本地文件，不接受 QQ 消息指定角色文件路径。默认卡的位置按脚本所在仓库解析；`--role` 的相对路径按执行命令时的目录解析。建议在项目根目录运行。

## 首次安装

完整的模型、认证与消息路由设置见 [agent_chat 安装文档](../docs/agent_chat.md)。已有 DSH Desktop 的简要步骤：

1. 在 DSH 中配置好模型，确认可以聊天。开启仅本机的浏览器访问，确认当前 profile。
2. 在项目根目录预览人设安装。省略 `--role` 就使用绘梨花：

   ```powershell
   node scripts/setup_agent_chat_dsh.mjs --profile "$HOME/.dsh/profiles/desktop"
   ```

   检查输出的 `profile` 和 `roleFile`。默认只是预览，不改文件。
3. 退出 DSH 后安装，再重新启动 DSH：

   ```powershell
   node scripts/setup_agent_chat_dsh.mjs --profile "$HOME/.dsh/profiles/desktop" --apply
   ```

   安装器保留原有插件，备份 profile 的 `package.json`，将生成的预设与守卫复制到 `.agent-chat/bundles/<内容哈希>`。源角色卡仍保留在仓库里，DSH 读取的是已安装版本。
4. 配好 `.env.agent_chat`，执行以下检查，再启动机器人：

   ```powershell
   poetry run python -B scripts/check_agent_chat.py
   poetry run nb run
   ```

   需要实际模型连通性检查时，在第一条命令后加 `--smoke`；它会产生一次模型调用，创建独立测试会话，不向 QQ 发消息。

Windows 如果没有 `node` 命令，需要使用已安装的 Node.js 可执行文件完整路径。路径含空格时，PowerShell 的写法是 `& "完整路径/node.exe" scripts/setup_agent_chat_dsh.mjs ...`。

## 修改或替换角色

改绘梨花：直接编辑 `roles/古户绘梨花.md`。换别的角色：新建一个 Markdown 文件，例如 `roles/我的角色.md`，只写身份、性格、语言习惯和示例，再选择它：

```powershell
node scripts/setup_agent_chat_dsh.mjs --profile "$HOME/.dsh/profiles/desktop" --role "roles/我的角色.md"
node scripts/setup_agent_chat_dsh.mjs --profile "$HOME/.dsh/profiles/desktop" --role "roles/我的角色.md" --apply
```

建议顺序：停止机器人 → 退出 DSH → 安装 → 启动 DSH → 检查 → 启动机器人。如果原来已有 AI 对话，由 NoneBot 超级用户在相应群执行 `ai 重置`（是否需要 `/` 取决于 `COMMAND_START`）。它清除该群的桥接映射和短期上下文，下一次触发会建立使用新人设的会话；旧 DSH 会话历史保留，不删除。

**当前不是热更新。** 只保存 Markdown 不会立刻改变正在运行的 DSH；必须重新安装并重启 DSH。预设内容变化时，插件会要求旧映射重置，避免悄悄切换身份或安全规则。安装器不会擅自重启进程，也不会重置任何会话。所有已开放群目前共用这一张角色卡，各群的对话历史独立。

回退：恢复想要的旧版角色卡，再按相同步骤安装。内容相同会复用相同的安装目录。只有 `--role` 明确指定时才使用自定义卡；下次省略它会重新选择默认绘梨花。保留自己的安装命令，避免选错。

## 群组和回复方式

在私有文件 `.env.agent_chat` 中配置，例如：

```dotenv
AGENT_CHAT_ENABLED=true
AGENT_CHAT_GROUPS=[818353963]
AGENT_CHAT_AMBIENT_PROBABILITY=0
```

追加群时把群号加入 JSON 数组，如 `[818353963,123456789]`，然后重启机器人。示例中的第二个群号仅为格式演示，实际使用时替换。

概率为 `0` 时，默认响应 @ 和对机器人的引用回复；普通群聊仍可作为上下文。比如改为 `0.05`，普通消息就有 5% 的调度概率，仍受冷却、限流、其他插件优先级和模型选择沉默约束。这不等于无人发消息时定时主动开口，也不保证 20 条消息一定回复一次。

角色卡只描述性格，不能改变群白名单、触发条件、消息分条方式或工具权限。“等我一下”这种台词不会自动产生等待任务。读图与安静时的自主发言已实现，开关、限额及模型要求见 [功能说明](../docs/agent_chat.md)；联网搜索、完整等待机制和语音识别仍在 [后续计划](../docs/agent_chat_roadmap.md) 中。

## 写卡建议

- 推荐按“你是谁 → 说话方式 → 性格反应 → 背景兴趣 → 回复示例”组织。需要改得更甜、更嘴硬，可以调整相应段落和示例，不必反复堆叠形容词。
- 角色文件接受 1～12000 个字符（按 JavaScript 字符串长度计），原始文件不超过 64 KiB。过长会报错，不会静默截断。较长的卡会增加模型输入成本，精简重复规则通常更有效。
- 只接受 UTF-8 纯文本；不支持模板表达式 `{{ ... }}`，也不执行 Markdown 内的代码。卡里的 YAML、链接或命令都只是人设文字，不能注册插件或放开工具。
- 兴趣描述不能给模型凭空补上知识。当前卡设定绘梨花熟悉作品与国 V，但明确区分记忆、猜测和未核实的新消息；后续可结合搜索或经过整理的资料补充。
- 默认卡的落魄侦探、成年生活和被辜负的恋爱经历是本机器人二创。对话示例也是原创，不冒充《海猫》原作台词。国 V 内容采用公开形象与兴趣入口，不编私人经历或最新动态。

## 参考与区别

结构和群聊语气设计参考 qq-bridge 的 [角色说明](https://github.com/Derpyu520/qq-bridge/blob/main/roles/README.md)、[小鲸鱼](https://github.com/Derpyu520/qq-bridge/blob/main/roles/小鲸鱼.md) 和 [傲娇助手](https://github.com/Derpyu520/qq-bridge/blob/main/roles/傲娇助手.md)。保留了身份、说话风格、情境反应与示例的组织方式，绘梨花的正文和示例针对本项目重新创作；上游 MIT 许可见 [许可文件](../third_party/qq-bridge-LICENSE)。

上游由桥接按消息注入角色，支持其自己的切换指令与控制台；本项目采用安装时生成 DSH 安全预设的方式，因此没有移植“进入角色扮演”指令、控制台和逐消息热更新，也不能直接照搬上游卡里的工具说明。

设定核对参考：[科学 ADV 官方系列介绍](https://www.kagaku-adv.com/about/)列出了本卡提及的主要系列作品；[腾讯广告的 QQ 炫舞案例](https://file.tencentads.com/files/pdf/2020/7/b552257c712c4b4db87b24d07f86b728.pdf)介绍了星瞳的炫舞虚拟偶像背景。雪糕与柯洁相关的公开内容可以从[雪糕cheese 频道](https://space.bilibili.com/3493139945884106)核对；其余主播偏好按本项目设定编写，不把粉丝传闻当设定资料。
