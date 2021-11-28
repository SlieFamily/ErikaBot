import nonebot
import re
from datetime import datetime,timedelta
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.adapters.cqhttp import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot.message import run_postprocessor
from nonebot.matcher import Matcher
import random

sarcasm = on_command("嘲讽",priority=3)
circle = on_command("专属时间",priority=5)
welcom = on_notice(priority=4)
suanle = on_regex("算了",priority=5)
ping = on_command("ping 胶布",priority=5)
pick = on_notice(priority=5)


@sarcasm.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    msg = str(event.get_message()).strip()
    if msg:
        state["msg"] = msg

@sarcasm.got("msg", prompt="？")
async def got_msg(bot: Bot,event: Event, state: T_State):
    msg = re.findall("([\u4E00-\u9FA5A-Za-z0-9_]+)，([\u4E00-\u9FA5A-Za-z0-9_]+)",str(state["msg"]))[0]
    # print(msg)
    send_msg = f"仅凭借{msg[0]}，古户绘梨花便能{msg[1]}到这种程度，如何呀，诸位~"
    await sarcasm.finish(Message(send_msg))

@circle.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    localtime = datetime.now()
    localtime += timedelta(hours=7)
    logger.info(str(localtime.hour))
    if localtime.hour == 16 and localtime.minute < 10:
        # logger.info(str(localtime.hour))
        await circle.finish(Message("现在，瓦达西，是，是属于你一个人的……"))

@welcom.handle()
async def handle(bot: Bot, event: GroupIncreaseNoticeEvent, state: T_State):
    user = event.get_user_id()
    at_ = "[CQ:at,qq={}]".format(user)
    # msg = at_+'新人，想学爆点吗？'
    msg = at_+'欢迎新人进裙~\n'
    await welcom.finish(Message(msg))

@pick.handle()
async def handle(bot: Bot, event: PokeNotifyEvent, state: T_State):
    msg = event.get_log_string()
    check = re.search("'target_id': 2523899329",msg)
    if check:
        await pick.finish(Message("贱民也想戳一戳我？"))
    await pick.finish()

@suanle.handle()
async def handle_first_receive(bot: Bot,event: Event, state: T_State):
    await suanle.finish(Message("要算卦了？"))

@ping.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    await ping.send(Message("正在 Ping github.com/ErikaBot [220.181.38.148] 具有 32 字节的数据:"))
    await ping.send(Message("220.181.38.148 的 Ping 统计信息:\n数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)"))
    await ping.send(Message("往返行程的估计时间(以毫秒为单位):\n最短 = 31ms，最长 = 32ms，平均 = 31ms"))
    await ping.finish()