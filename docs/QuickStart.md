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
