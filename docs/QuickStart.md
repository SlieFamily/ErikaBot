# Bot部署全流程 For Linux

## 服务器支撑

### 支持IPv4访问

Linux 可通过 `curl -4 ipinfo.io` 验证是否支持IPv4网络

> （可选）没有 `curl` 可直接 `apt-get` 安装

若服务器为 Only IPv6 可通过安装 ***TWRP*** 实现：

```shell
wget -N https://raw.githubusercontent.com/fscarmen/warp/main/menu.sh && bash menu.sh
```

---

以下要求均属于本地部署签名服务器所需要求，若有可信赖的第三方qsign地址可忽略。

### 支持JDK（版本1.8或以上）

Linux 可通过 `java --version` 验证是否安装有 Java 环境，用于运行QQ签名服务器（QQsign）

> 此处提供 `jdk-8u144-linux-x64.tar` 的 [下载链接](https://pan.baidu.com/s/10TxlxW0t742Sf42_VxAP3w?pwd=zzkt)
>
> 参考安装教程：https://blog.csdn.net/weixin_41786879/article/details/126603440

### GLIBC版本2.17以上

Linux 可通过如下方法查看现在的 `glibc` 版本，版本未达到标准需升级以运行QQ签名服务器（QQsign）

```shell
strings /lib64/libc.so.6 | grep GLIBC
ldd --version
```

## 环境搭建

> 1. 本项目基于 `go-cqhttp`[文档](https://docs.go-cqhttp.org/) 进行QQ登录；
> 1. 本项目基于 `unidbg-fetch-qsign`~~[文档(已删库)](https://github.com/fuqiuluo/unidbg-fetch-qsign/wiki)~~ , [备份仓库](https://github.com/touchscale/Qsign/tree/master) 部署QQ签名服务器；
> 1. 本项目基于 `nonebot2`[文档](https://v2.nonebot.dev/) 进行Bot自动化；
> 1. 本项目基于 `Python3`部分的依赖库.
### 后端框架安装

阅读相关框架文档，配置反向`ws`客户端、必要的`.env`相关设置、`android_id`和QQ版本同步、服务器端口等。

> **2023.7.24 实测**
>
> > 当前可通过 `go-cqhttp v1.1.0` + `qsign v1.1.0` + `nonebot2 v2.0.1` 完美部署
>
> **2023.8.7 实测**
>
> > 可通过 `go-cqhttp 5db03c7 dev`+`qsign v1.1.7`+`nonebot2 v2.0.1` 完美部署
> >
> > - 需在`cq/config.yml` 中增加配置：[详见 #2304](https://github.com/Mrs4s/go-cqhttp/issues/2304)
> > - 需在`txlib/8.9.63/config.json`中`"auto_register": true,` 端口号根据需要修改
>
> **2023.12.21 实测**
>
> > 当前可通过 `go-cqhttp v1.2.0`+`qsign v1.2.0`+`nonebot2 v2.0.1` 完美部署
> >
> > - 需找到对应版本号（如：8.9.90）的 `android_xxx.json` 文件（如`android_pad.json`）【[仓库](https://github.com/MrXiaoM/qsign/tree/mirai)】
> > - 手动将 `json` 文件重命名为 `6.json`（6表示Pad）放在 `go-cqhttp`项目目录 `root/data/versions`下。[详见#2481](https://github.com/Mrs4s/go-cqhttp/issues/2481)
> > - 在`txlib/8.9.90/config.json`中`"auto_register": true,` 端口号根据需要修改

### 前端Bot安装

1. `git clone`本项目；
2. 安装 `poetry` 依赖包管理工具；
3. 通过 `poetry install` 安装 bot 项目目录下所有python依赖.

## 快速启动

### 安装 `screen` 实现服务并行

### (可选)启动签名服务器

在`qsign`目录下通过如下命令启动

```shell
bash bin/unidbg-fetch-qsign --basePath=txlib/8.9.90
```

### 启动 go-cqhttp

在`go-cqhttp` 目录下通过如下命令启动

```
./go-cqhttp --faststart
```

首次启动时，根据提示在 `config.json` 和 `device.json` 中同步 QQsign 的内容

> 🔔首次启动有账号**冻结**风险，此后长时间可用，但存在玄学

> 2023.12.21 更新：
>
> 再次需要验证码登录时，选择自动获取token(`方式1`)的方法失效；手动输入`ticket`的方法会白屏(`方式2`). 解决方法见 [#2459](https://github.com/Mrs4s/go-cqhttp/issues/2459)



### 启用虚拟环境运行机器人

1. 进入bot虚拟环境 `poetry shell`
2. `nb run`运行机器人即可
