# 快速部署Bot

## 环境依赖

> 1. 本项目基于 `napcat`[文档](https://napneko.github.io/guide/napcat) 进行QQ登录；
> 1. 本项目基于 `nonebot2`[文档](https://v2.nonebot.dev) 进行Bot自动化；
> 1. 本项目基于 `Python3`部分的依赖库.
### QQ框架安装

参考**官方文档**安装并登录机器人QQ，通过WebUI新增Websocket客户端，设置反向`ws`：`ws://localhost:8080/onebot/v11/ws` ，填写`token`字段，最后保存并启用。

### 前端Bot安装

1. `git clone`本项目；
2. 安装 `poetry` 依赖包管理工具；
3. 通过 `poetry install` 安装 bot 项目目录下所有python依赖（见`pyproject.toml`）；
4. 编辑根目录下的 `.env.prod` 文本文件，确保IP和端口号与QQ框架的配置一致，注意`ONEBOT_ACCESS_TOKEN=你在 NapCat 中配置的 token` 字段的填写。

## 快速启动

1. 运行napcat，如 Windows系统下运行`napcat.quick.bat`
2. 进入bot虚拟环境 `poetry shell` 或 `poetry env activate`
3. `nb run`运行机器人即可

## 可选：启用 DSH 角色聊天

基础机器人成功连接 NapCat 后，再按 [agent_chat 安装说明](agent_chat.md) 配置 DSH 模型、安装专用安全预设，并创建私有 `.env.agent_chat`。LLM API Key 填在 DSH；插件配置仅保存本机 DSH 连接凭据、允许群和功能开关。`.env.prod` 已被 Git 跟踪，不要将 DSH 凭据或模型 Key 写入其中。

默认角色是 [古户绘梨花](../roles/古户绘梨花.md)。安装预设后，按需打开读图、随机接话与自主发言；每个群有独立持久会话，人设首次载入、普通轮次增量发送。角色替换和追加群的步骤见 [角色设置说明](../roles/README.md)。

日常启动也可以直接使用 `poetry run nb run`，无须手动进入虚拟环境。

运行后怎样识别进程、查看/导出日志，见 [运行进程与日志](agent_chat.md#运行进程与日志)。更换模型 Key 通常只需在 DSH 操作；更改插件私有配置则需重启 NoneBot，详细步骤见 [更换 API、Key 或模型](agent_chat.md#更换-apikey-或模型)。DSH 暂停或退出时的 AI 行为与恢复方法见 [DSH 关闭、断线与恢复](agent_chat.md#dsh-关闭断线与恢复)。

开发测试期间保持现有机器人和 QQ 网关在线：离线测试使用临时数据库与模拟收发，真实 DSH 联调用独立实例/会话。只在正式部署完成且验证通过后重启需要加载变更的进程，详见 [在线测试与部署](agent_chat.md#保持-qq-在线的测试与部署)。联网使用 DSH 已安装的 AnySearch 插件；首次迁移需安装新的安全预设并重启 DSH 与 NoneBot，之后只改 `AGENT_CHAT_SEARCH_ENABLED` 等开关时只需重启 NoneBot。凭据、额度与迁移见 [AnySearch 搜索配置与边界](agent_chat.md#ai-自主联网搜索anysearch)。
