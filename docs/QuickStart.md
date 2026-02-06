# 快速部署Bot

## 环境依赖

> 1. 本项目基于 `napcat`[文档](https://docs.go-cqhttp.org/) 进行QQ登录；
> 1. 本项目基于 `nonebot2`[文档](https://v2.nonebot.dev/) 进行Bot自动化；
> 1. 本项目基于 `Python3`部分的依赖库.
### 后端框架安装

阅读相关框架文档，配置反向`ws`客户端、必要的`.env`相关设置、`android_id`和QQ版本同步、服务器端口等。

### 前端Bot安装

1. `git clone`本项目；
2. 安装 `poetry` 依赖包管理工具；
3. 通过 `poetry install` 安装 bot 项目目录下所有python依赖.

## 快速启动

### 安装 `screen` 实现服务并行

> https://github.com/Mrs4s/go-cqhttp/issues/2459)

### 启用虚拟环境运行机器人

1. 进入bot虚拟环境 `poetry shell`
2. `nb run`运行机器人即可
