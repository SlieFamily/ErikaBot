import nonebot
import json
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.adapters.cqhttp import Message,MessageSegment


help_msg = """欢迎使用Erikabot！
本胶布拥有的功能有：
----------
1.语录放送
2.美图分享（不是真涩图哦）
3.BV/av号转小程序（检修中）
4.网易云点歌
5.考研倒计时
6.群表情包（检修中）
7.推特关注推送
----------
- 通过“twitter帮助”命令查看tweet设置"""

helper = on_command("/help", aliases=set(['帮助']), priority=2)

@helper.handle()
async def handle_first_receive(bot: Bot, event: Event, state: T_State):
    await helper.finish(Message(help_msg))
