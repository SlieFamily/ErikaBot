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

# 布置棋盘 |<sub>[快速开始](docs/QuickStart.md)</sub>

> 1. 本项目基于 `go-cqhttp`[文档](https://docs.go-cqhttp.org/) 进行QQ登录；
> 1. 本项目基于 `unidbg-fetch-qsign`[文档](https://github.com/fuqiuluo/unidbg-fetch-qsign/wiki) 部署QQ签名服务器；
> 1. 本项目基于 `nonebot2`[文档](https://v2.nonebot.dev/) 进行Bot自动化；
> 1. 本项目基于 `Python3`部分的依赖库.

# 魔导书|<sub>[详细功能介绍](docs/ToolList.md)</sub>

#### ErikaBot 帮助菜单|暂定

> 命令中出现的**中括号**在使用时不需要添加

**嘲讽**  `嘲讽 [语句A]，[语句B]`

**嘴香** 尝试`@`本bot或者`戳一戳`本bot即可（管理员可通过 `开启/关闭嘲讽状态` 进行控制）

**奥利奥** `来点 ['奥'和'利'的组合词（超过一个字）] `

**望文声义** `请说：[需要朗读的文字]`

**隔空喊话** `QQ回复[需要匿名发送的内容，图片/表情等]：隔空喊话to<空格>[Bot所在的QQ群号]`

**美图发送** 命令：`setu|涩图|色图|来点涩图`（图发完之后**再**接一句`不够色` ~~或者`加大剂量`~~ 试试）

**语录清单** `侦探的棋子名单` 对应 *普通语录清单*
				`侦探的魔女名单` 对应 *高级语录清单*
				`[语录名称]语录(-n)` 则回复随机/第 $n$ 条该语录的记录

**添加语录** `QQ回复[需要加入语录的内容，图片/表情等]：add[语录名称]语录`

**删除语录** `del [语录名称]语录-n` 删除第 $n$ 条语录

**查找语录** `find：[需要查找的语录内容]`

**高级语录** 若`[语录名称]`中带`<高级>`的后缀，则触发关键词即可回复随机语录

​                如：`发送：今天吃什么` 则`回复：紫菜蛋花汤`

**RSS订阅** `完美验尸！`查看本群关注清单，`验尸[app名称]：[用户ID]`进行关注（当前支持 微博、B站、推特）

**倒计时** 每天8点**自动提醒**相关考试或日程的剩余天数

​             也可以通过`倒计时`、`考试`等命令触发

## 待更

