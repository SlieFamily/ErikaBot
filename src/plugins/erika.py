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
ping = on_command("QQ通行证",priority=5)
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
    # await ping.send(Message("正在 Ping github.com/ErikaBot [220.181.38.148] 具有 32 字节的数据:"))
    # await ping.send(Message("220.181.38.148 的 Ping 统计信息:\n数据包: 已发送 = 4，已接收 = 4，丢失 = 0 (0% 丢失)"))
    # await ping.send(Message("往返行程的估计时间(以毫秒为单位):\n最短 = 31ms，最长 = 32ms，平均 = 31ms"))
    msg = [{'type':'xml','data':{}}]
    
    #data = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><msg serviceID="1"><item><title>[QQ频道]命运石之门 — STEINS;GATE </title></item><source name="频道通行证(破解版)" icon="https://qzs.qq.com/ac/qzone_v5/client/auth_icon.png" action="" appid="-1" /></msg>'
    
    data = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><msg serviceID="1" templateID="2" action="web" brief="[QQ频道]通行证" sourceMsgId="2" url="https://qun.qq.com/qqweb/qunpro/share?_wv=3&_wwv=128&inviteCode=H094H&from=246610&biz=ka" flag="3" adverSign="0" multiMsgFlag="0"><item layout="5" advertiser_id="0" aid="0"><picture cover="https://gchat.qpic.cn/gchatpic_new/1269416542/729901771-3068461129-D39946C4CA84A50A7FE9E5B688AB52E8/0?term=2" w="0" h="0" /></item><item layout="6" bg="-1" advertiser_id="0" aid="0"><summary size="27" style="1">☞点击这里☜

进入石头门QQ频道~ ٩(๑ᵒ̴̶̷͈᷄ᗨᵒ̴̶̷͈᷅)و</summary></item><source name="" icon="" action="" appid="-1" /></msg>'''

    msg[0]['data']['data'] = data

    await ping.finish(Message(msg))