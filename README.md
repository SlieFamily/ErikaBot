<!-- markdownlint-disable MD033 MD041-->

<p align="center">
  <img src="https://i.loli.net/2021/11/28/AsUmeoSyqzjNCZr.png" width="200" height="200"/>
</p>
<div align="center">

# 绘梨花(胶布)Bot|<sub>ErikaBot</sub>
<!-- markdownlint-disable-next-line MD036 -->
_✨ 基于NoneBot2的绘梨花多功能 Bot ，自用 ✨_

</div>

## 快速开始

1. 参考`go-cqhttp`项目[文档](https://docs.go-cqhttp.org/)，配置好机器人的相关设置，以及反向`ws`客户端
2. 参考`nonebot2`项目[文档](https://v2.nonebot.dev/)，添加必要的`.env`相关设置
3. 安装本项目相关的依赖库（[依赖清单]()）
4. `git clone`本项目，在项目目录下`nb run`运行机器人即可

## 功能清单

### 0.绘梨花特性

#### 嘲讽

命令（注意是**中文逗号**`，`）：

```shell
嘲讽 [语句A]，[语句B]
```

返回：

```
仅凭借[语句A]，古户绘梨花便能[语句B]到这种程度，如何呀，诸位~
```

#### 互动

尝试`@`本bot或者`戳一戳`本bot即可

##### 如何添加/删除`@`之后的回复

```bash
add Erika嘴臭 '[需要添加的语录]'
del Erika嘴臭 '[需要添加的语录]'
```

### 1.语录放送

> 基于`sqlite3`**轻量数据库**的自定义语录放送功能

#### 发送语录

```bash
[语录名称]语录
```

通过上述命令直接触发随机语录。其中，`[语录名称]`是用于检索的关键词，如：

发送命令：`战人语录`，如果数据库中已有该语录，则可以在存入的语录中随机发送一条

#### 添加语录

```shell
add [语录名称]语录 '[需要加入该语录的内容，可以是图片/表情等]'
```

#### 删除语录

```bas
del [语录名称]语录 '[需要加入该语录的内容，可以是图片/表情等]'
```

#### 设置对指定群不可见

> 只对`SUPERUSERS`的命令进行响应

```shell
lock to [语录名称]语录
unlock to [语录名称]语录
```

#### 设置宏观触发

> 只对`SUPERUSERS`的命令进行响应

```bash
update rule [语录名称]语录
```

开启该功能后可以不用加上后缀`语录`，并且只要一句话中含有`[语录名称]`即可触发，如：

发送一句话`我真的好喜欢战人呀~`，机器人检索到`战人`二字后，会随机发送一句隶属于`战人迫害语录`中的一句话。

**由此可见，对于宏观触发的语录，需要在创建时使用`[语录名称]迫害语录`进行追加**

### 2.推特更新推送

> 基于`phantomjs`进行爬虫实现
>
> 原项目地址：[nonebot-twitter](https://github.com/kanomahoro/nonebot-twitter)

本功能可实现对关注列表中的对象进行实时监控，一旦发送推文立刻到指定群里进行转发提醒（每个群可独立设置关注名单）

> 只对`SUPERUSERS`和`ADMIN`的命令进行响应

```bash
@[bot] 关注列表
@[bot] 给爷关注 [推特ID]
@[bot] 取关 [推特ID]
```

### 3.倒计时

每天8点**自动提醒**相关考试或日程的剩余天数

也可以通过`倒计时`、`考试`等命令触发

### 4.奥利奥

> 原项目地址：[Oreoooo](https://github.com/C-Jun-GIT/Oreo)

通过命令触发：

```
来点/来一份/order ['奥'和'利'的组合词（超过一个字）] 
```

效果展示：

<p align="center">
  <img src="https://i.loli.net/2021/11/28/hDW5YtjEMBX6lxK.jpg" width="400"/>
</p>
<div align="center">

注：输入`奥利给`或者字串超过50字有**彩蛋**

### 5.美图分享

