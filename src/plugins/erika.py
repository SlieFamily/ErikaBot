import nonebot
import re
import time
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
welcom = on_notice(priority=4)
# suanle = on_regex("算了",priority=5)
selfIntro = on_command("来点自我介绍",priority=4)
ping = on_command("QQ通行证",priority=5)
poke = on_notice(priority=5)
helper = on_command("/help", aliases=set(['帮助']), priority=2)
red_true = on_regex("((#[0-9,a-f,A-F]{6})真实|(虚妄)真实|(红色)真实|(蓝色)真实|(金色)真实)：([\w\W]+)",priority=3)

@sarcasm.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    msg = str(event.get_message()).strip()
    if msg:
        state["msg"] = msg

@sarcasm.got("msg", prompt="？")
async def got_msg(bot: Bot,event: Event, state: T_State):
    msg = re.findall("([\s\S]+)，([\s\S]+)",str(state["msg"]))[0]
    # print(msg)
    send_msg = f"仅凭借{msg[0]}，古户绘梨花便能{msg[1]}到这种程度，如何呀，诸位~"
    await sarcasm.finish(Message(send_msg))

@welcom.handle()
async def handle(bot: Bot, event: GroupIncreaseNoticeEvent, state: T_State):
    user = event.get_user_id()
    at_ = "[CQ:at,qq={}]".format(user)
    # msg = at_+'新人，想学爆点吗？'
    msg = at_+'欢迎新人进裙~'
    await welcom.finish(Message(msg))

@poke.handle()
async def handle(bot: Bot, event: PokeNotifyEvent, state: T_State):
    msg = event.get_log_string()
    check = re.search("'target_id': 2523899329",msg)
    rsp = [f'[CQ:poke,type=1,id=-1,name="戳一戳",qq={event.get_user_id()}]','贱民也想戳一戳我？','再戳？']
    if check:
        await poke.finish(Message(random.choice(rsp)))
    await poke.finish()

@selfIntro.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    await selfIntro.send(Message("初次见面，你好"))
    time.sleep(1)
    await selfIntro.send(Message("我的名字叫做 古户绘梨花"))
    time.sleep(1)
    await selfIntro.send(Message("虽然是位不速之客，还请多加欢迎"))
    time.sleep(1)
    msg = str(event.get_message()).strip()
    if msg:
        state["msg"] = msg

@selfIntro.got("msg", prompt="我乃来访者，六轩岛上的，第18名人类！！")
async def got_msg(bot: Bot,event: Event, state: T_State):
    msg = re.findall("17人",str(state["msg"]))[0]
    print(msg)
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
async def handle(bot: Bot, event: Event, state: T_State):
#     msg = [{'type':'xml','data':{}}]
#     data = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><msg serviceID="1" templateID="2" action="web" brief="[QQ频道]通行证" sourceMsgId="2" url="https://qun.qq.com/qqweb/qunpro/share?_wv=3&_wwv=128&inviteCode=BS7Tt&from=246610&biz=ka" flag="0" adverSign="0" multiMsgFlag="0"><item layout="5" advertiser_id="0" aid="0"><picture cover="https://gchat.qpic.cn/gchatpic_new/1269416542/729901771-3068461129-D39946C4CA84A50A7FE9E5B688AB52E8/0?term=2" w="0" h="0" /></item><item layout="6" bg="-1" advertiser_id="0" aid="0"><summary size="27" style="1">☞点击这里☜

# 进入石头门QQ频道~ ٩(๑ᵒ̴̶̷͈᷄ᗨᵒ̴̶̷͈᷅)و</summary></item><source name="" icon="" action="" appid="-1" /></msg>'''
#     msg[0]['data']['data'] = data

    msg = [{'type':'json','data':{}}]
    data = '''{"app":"com.tencent.qun.pro","desc":"","view":"contact","ver":"1.0.0.0","prompt":"邀请你加入QQ频道","appID":"","sourceName":"","actionData":"","actionData_A":"","sourceUrl":"","meta":{"contact":{"appId":"xxx","biz":"ka","desc":"The End of Messenger邀请你加入QQ频道“命运石之门 Steins;Gate”，进入可查看详情。","jumpUrl":"https:\/\/qun.qq.com\/qqweb\/qunpro\/share?_wv=3&_wwv=128&inviteCode=BS7Tt&from=246610&biz=ka","preview":"https:\/\/groupprohead-76292.picgzc.qpic.cn\/28505721637064109\/0?t=1637755895495","tag":"QQ频道","title":"邀请你加入QQ频道"}},"config":{"autosize":1,"ctime":1639742137,"token":"5adb393f140035b5413626b0604570ec"},"text":"","extra":""}
'''
    msg[0]['data']['data'] = data
    await ping.finish(Message(msg))

@helper.handle()
async def handle_first_receive(bot: Bot, event: Event, state: T_State):
    help_msg = [{'type':'xml','data':{}}]
    data = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><msg serviceID="1" templateID="-1" action="" brief="[胶布bot]帮助菜单" sourceMsgId="0" url="" flag="3" adverSign="0" multiMsgFlag="0"><item layout="2" mode="1" bg="-18751" advertiser_id="0" aid="0"><picture cover="https://gchat.qpic.cn/gchatpic_new/1364374624/3808573830-2554273412-B8EDB73485FB0C183EBB095ECF4BAE54/0?term=3" w="0" h="0" /><title>绘梨花Bot</title><summary>帮助菜单</summary></item><item layout="6" advertiser_id="0" aid="0"><summary size="28" color="#ff69b4">
[嘲讽]：使用 嘲讽 aaaa，bbbb 以触发

[互动]：请@，或者戳一戳

[真实]：发送 xx真实：zzzz 以触发

[美图]：
    发送'涩图'、'来点涩图'等触发
        (回复'不够色'有惊喜)

[奥利奥]：来点 奥利*

[语录]：   
    -添加 add xx语录：zzzzzz
    -查找 find：zzzzz (支持模糊查找)
    -删除 del xx语录：zzzzzz

[倒计时]：每天8点自动发送

[点歌]：发送'点歌 xxx'

[推特]：
    发送'twitter帮助'查看更多</summary><hr hidden="false" style="0" /></item><source name="by-Slie" icon="http://t.cn/RVIeaZK" url="http://github.com/sliefamily/erikabot" action="" appid="0" /></msg>'''
    help_msg[0]['data']['data'] = data
    await helper.finish(Message(help_msg))

@red_true.handle()
async def handle(bot: Bot, event: Event, state: T_State):
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
    data = f'''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><msg serviceID="1" templateID="-1" action="plugin" a_actionData="" brief="[红色真实]{msg}" sourceMsgId="0" url="" flag="2" adverSign="3" multiMsgFlag="0"><item layout="9" bg="2" advertiser_id="0" aid="0"><picture cover="https://gchat.qpic.cn/gchatpic_new/1364374624/3808573830-2554273412-B8EDB73485FB0C183EBB095ECF4BAE54/0?term=3" w="0" h="0" /></item><item layout="6" advertiser_id="0" aid="0">
<summary size="100" color="{color}">{msg}</summary></item><source name="" icon="" action="" appid="-1" /></msg>'''
    send_msg[0]['data']['data'] = data
    await red_true.finish(Message(send_msg))