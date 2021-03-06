import nonebot
import re
import time
from datetime import datetime,timedelta
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.params import State, ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent,GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot.message import run_postprocessor
from nonebot.matcher import Matcher
import random

sarcasm = on_command("嘲讽",priority=3)
welcom = on_notice(priority=4)
# suanle = on_regex("算了",priority=5)
selfIntro = on_command("来点自我介绍",priority=4)
ping = on_command("QQ通行证",priority=5)
poke = on_notice(priority=5)
say = on_command("请说：",priority=3)
helper = on_command("/help", priority=2)
red_true = on_regex("((#[0-9,a-f,A-F]{6})真实|(虚妄)真实|(红色)真实|(蓝色)真实|(金色)真实)：([\w\W]+)",priority=3)

@sarcasm.handle()
async def handle(bot: Bot, event: Event, state: T_State = State(), msg:Message = CommandArg()):
    if msg:
        state["msg"] = msg

@sarcasm.got("msg", prompt="？")
async def got_msg(bot: Bot,event: Event, msg:Message = Arg("msg")):
    msg = re.findall("([\s\S]+)，([\s\S]+)",str(msg))[0]
    # print(msg)
    send_msg = f"仅凭借{msg[0]}，古户绘梨花便能{msg[1]}到这种程度，如何呀，诸位~"
    await sarcasm.finish(Message(send_msg))

@welcom.handle()
async def handle(bot: Bot, event: GroupIncreaseNoticeEvent, state: T_State = State()):
    user = event.get_user_id()
    at_ = "[CQ:at,qq={}]".format(user)
    # msg = at_+'新人，想学爆点吗？'
    msg = at_+'欢迎新人进裙~'
    await welcom.finish(Message(msg))

@poke.handle()
async def handle(bot: Bot, event: PokeNotifyEvent, state: T_State = State()):
    msg = event.get_log_string()
    check = re.search("'target_id': 2523899329",msg)
    rsp = [f'[CQ:poke,type=1,id=-1,name="戳一戳",qq={event.get_user_id()}]','贱民也想戳一戳我？','再戳？']
    if check:
        await poke.finish(Message(random.choice(rsp)))
    await poke.finish()

@selfIntro.handle()
async def handle(bot: Bot, event: Event, state: T_State = State(), msg: Message = CommandArg()):
    await selfIntro.send(Message("初次见面，你好"))
    time.sleep(1)
    await selfIntro.send(Message("我的名字叫做 古户绘梨花"))
    time.sleep(1)
    await selfIntro.send(Message("虽然是位不速之客，还请多加欢迎"))
    time.sleep(1)
    if msg:
        state["msg"] = msg

@selfIntro.got("msg", prompt="我乃来访者，六轩岛上的，第18名人类！！")
async def got_msg(bot: Bot,event: Event, state: T_State = State(), msg: Message = Arg("msg")):
    msg = re.findall("17人",str(msg))[0]
    if msg:
        songContent = [
            {
                "type": "music",
                "data": {
                    "type": 163,
                    "id": 786015
                }
            }
        ]
        await selfIntro.finish(Message(songContent))
    else:
        await selfIntro.finish()


@ping.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
    msg = [{'type':'json','data':{}}]
    data = '''{"app":"com.tencent.qun.pro","desc":"","view":"contact","ver":"1.0.0.0","prompt":"邀请你加入QQ频道","appID":"","sourceName":"","actionData":"","actionData_A":"","sourceUrl":"","meta":{"contact":{"appId":"xxx","biz":"ka","desc":"The End of Messenger邀请你加入QQ频道“命运石之门 Steins;Gate”，进入可查看详情。","jumpUrl":"https:\/\/qun.qq.com\/qqweb\/qunpro\/share?_wv=3&_wwv=128&inviteCode=BS7Tt&from=246610&biz=ka","preview":"https:\/\/groupprohead-76292.picgzc.qpic.cn\/28505721637064109\/0?t=1637755895495","tag":"QQ频道","title":"邀请你加入QQ频道"}},"config":{"autosize":1,"ctime":1639742137,"token":"5adb393f140035b5413626b0604570ec"},"text":"","extra":""}
'''
    msg[0]['data']['data'] = data
    await ping.finish(Message(msg))


@red_true.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
    msg = state["_matched_groups"]
    rgb_dirc = {'虚妄':'#ffffff','红色':'#ff6347','蓝色':'#7f00ff','金色':'#d9d919'}
    color = rgb_dirc['虚妄']
    for i in msg:
        if i in ['虚妄','红色','蓝色','金色']:
            color = rgb_dirc[i]
            pass
        elif i != None and i != msg[-1]:
            color = i
            pass
    msg = msg[-1]
    if event.get_user_id() not in ['1364374624','2450509502'] and color == '#d9d919':
        await red_true.finish(Message('GameMaster岂是你能冒充的？'))
    send_msg = [{'type':'xml','data':{}}]
    data = f'''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><msg serviceID="1" templateID="-1" action="plugin" a_actionData="" brief="[真实]{msg}" sourceMsgId="0" url="" flag="2" adverSign="3" multiMsgFlag="0"><item layout="9" bg="2" advertiser_id="0" aid="0"><picture cover="https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_logo.png" w="0" h="0" /></item><item layout="6" advertiser_id="0" aid="0">
<summary size="100" color="{color}">{msg}</summary></item><source name="" icon="" action="" appid="-1" /></msg>'''
    send_msg[0]['data']['data'] = data
    await red_true.finish(Message(send_msg))

@say.handle()
async def handle(bot: Bot, event: GroupMessageEvent, state: T_State = State(),text: Message = CommandArg()):
    if text:
        state["text"] = text

@say.got("text", prompt="无论说什么我都会照做的~")
async def got_name(bot: Bot,event: Event, state: T_State = State(),text: Message = Arg("text")):
    if text:
        if len(text) <= 100:
            await say.finish(Message(f'[CQ:tts,text={text}]'))
        else:
            await say.finish(Message('说匿🐎，太长了！'))
    await say.finish()