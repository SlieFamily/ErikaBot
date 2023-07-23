<!-- markdownlint-disable MD033 MD041-->

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_logo.png" width="200" height="200"/>
</p>
<div align="center">

# 绘梨花(胶布)Bot|<sub>ErikaBot</sub>
<!-- markdownlint-disable-next-line MD036 -->
_✨ 基于NoneBot2的绘梨花多功能Bot，自用 ✨_

</div>



> #### 本Bot 已同步支持 **QQ** **频道** 的使用

# 部署 |<sub>[快速开始](docs/QuickStart.md)</sub>

# 功能清单

## 小结

#### ErikaBot 帮助菜单|暂定

> 命令中出现的**中括号**在使用时不需要添加

**嘲讽**  `嘲讽 [语句A]，[语句B]`

**嘴香** 尝试`@`本bot或者`戳一戳`本bot即可

**奥利奥** `来点 ['奥'和'利'的组合词（超过一个字）] `

**望文声义** `请说：[需要朗读的文字]`

**美图发送** 命令：`setu`、`涩图`、`色图`、`来点涩图`

**添加语录** `add [语录名称]语录：[需要加入该语录的内容，可以是图片/表情等]`

**删除语录** `del [语录名称]语录：[需要删除该语录的文本，不可以是图片]`

**查找语录** `find：[需要查找的语录内容]`

**高级语录** 上述`[语录名称]`中，带`<高级>`的后缀即可

​                如：`add 战人<高级>语录：不行啊，完全是不行啊！`

**推特发送** `twitter帮助`以查看

**倒计时** 每天8点**自动提醒**相关考试或日程的剩余天数

​             也可以通过`倒计时`、`考试`等命令触发

---

## 绘梨花特性

### 欢迎新人

顾名思义

### 嘲讽

命令（注意是**中文逗号**`，`）：

```shell
嘲讽 [语句A]，[语句B]
```

返回：

```
仅凭借[语句A]，古户绘梨花便能[语句B]到这种程度，如何呀，诸位~
```

### ~~嘴香~~（已取消）

尝试`@`本bot或者`戳一戳`本bot即可

#### 如何添加/删除`@`之后的回复

```bash
add Erika语录：[需要添加的语录]
del Erika语录：[需要添加的语录]
```

> 注意是**中文冒号**`：`，需要添加的语录前后**没有**中括号`[]`，下同

### 望文声义

> 调用`tts`进行自定义**文字朗读**

命令（注意是**中文冒号**`：`）：

```bash
请说：[需要朗读的文字]
```

* **注1：文本超过100个字符有惊喜~**
* 注2：由于调用的是`CQ码`，所以对文字中出现的**半角符号**转义时可能出现bug，待修复

### ~~红字真实~~（已失效）

命令（注意是**中文冒号**`：`）：

```bash
红色真实：[需要发送的真实]
蓝色真实：[需要发送的真实]
金色真实：[需要发送的真实]
虚妄真实：[需要发送的真实]
#ff00ff真实：[需要发送的真实]
```

- 颜色可以用16进制RGB码任意选取，如上述演示的`#ff00ff`
- 金色真实只有被设置为`Game Master`的用户可以触发，设置方式见下文

#### **效果展示**：

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@1.0.2/ErikaTest/TheTruth.jpg" width="400"/>
</p>


## 语录放送

> 基于`sqlite3`**轻量数据库**的自定义语录放送功能

### 语录清单

命令：

```bash
语录清单
高级语录清单
```

* 注：当数据量较大时会**极度刷屏**，请谨慎使用（待优化刷屏问题）

### 发送语录

```bash
[语录名称]语录
```

通过上述命令直接触发随机语录。其中，`[语录名称]`是用于检索的关键词，如：

发送命令：`战人语录`，如果数据库中已有该语录，则可以在存入的语录中随机发送一条

### 添加语录

```shell
add [语录名称]语录：[需要加入该语录的内容，可以是图片/表情等]
```

### 删除语录

```bas
del [语录名称]语录：[需要删除该语录的内容，可以是图片/表情等]
```

### 合并语录

```bash
merge [语录名称1]语录，[语录名称2]语录
```

* 将 *语录2* 与 *语录1* 合并为 *语录1*，并将 *语录2* 删除

### 销毁语录

> 只对`SUPERUSERS`的命令进行响应

```bash
drop [语录名称]语录
```

* **将整个语录全部删除**

### 查找添加者

> 支持**模糊匹配**

```bash
find：[需要查找的语录内容，可以是图片/表情等]
```

### 设置不可见

> 只对`SUPERUSERS`的命令进行响应

```shell
lock to [语录名称]语录
unlock to [语录名称]语录
```

### 设置 *高级语录触发*

开启该功能后可以不用加上**后缀** `语录`，并且只要一句话中**含有**`[语录名称]`即可触发，如：

发送：`我真的好喜欢战人呀~`；机器人检索到`战人`二字后，会随机发送一句隶属于`战人<高级>语录`中的语句。

**对于高级语录，需要在创建时使用`[语录名称]<高级>语录`进行追加**

>当前 **数据库**(`anas.db`) 中由群友自主实现的**高级语录库**
>
>
>|                             命令                             |        介绍        |
>| :----------------------------------------------------------: | :----------------: |
>| `黄金魔女碑文`、`诺克斯十诫`、`侦探十二守则`、`海猫CG库`、…… |    **海猫特色**    |
>|                `闪电旋风劈`、`雷霆半月斩`、……                | **洛洛历险记招式** |
>|         `今天吃什么`、`今天喝什么`、`今晚和谁睡`、……         |     **报菜名**     |
>|       `乌帕墩墩`、`胶布墩墩`、`力士墩墩`、`墩墩噜`、……       |   **冰墩墩变种**   |
>|                              ……                              |         ……         |



## ~~推特更新推送~~（监修中）

> 基于`Selenium`自动化爬虫实现
>
> **参考**项目地址：[nonebot-twitter](https://github.com/kanomahoro/nonebot-twitter)

本功能可实现对关注列表中的对象进行实时监控，一旦发送推文立刻到指定群里进行转发提醒（每个群可**独立设置**关注名单）

> 只对`SUPERUSERS`和`ADMIN`的命令进行响应

```bash
@[bot] 关注列表
@[bot] 给爷关注 [推特ID]
@[bot] 取关 [推特ID]
```

## 倒计时

每天8点**自动提醒**相关考试或日程的剩余天数

也可以通过`倒计时`、`考试`等命令触发

## 奥利奥

> **参考**项目地址：[Oreoooo](https://github.com/C-Jun-GIT/Oreo)

通过命令触发：

```
来点/来一份/order ['奥'和'利'的组合词（超过一个字）] 
```

效果展示：

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@1.0.2/ErikaTest/Oreoooo.jpg" width="400"/>
</p>



注：输入`奥利给`或者字串超过50字有**彩蛋**

## ~~美图分享~~（监修中）

通过命令`setu`、`涩图`、`色图`、`来点涩图`触发

> PS：【**其他互动**】胶布发送美图后，再使用`不够色`命令，有惊喜

## ~~网易云点歌~~（已失效）

## 待更
