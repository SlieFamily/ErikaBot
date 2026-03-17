import nonebot
import re
import time
from datetime import datetime,timedelta
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.params import ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent,GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot.message import run_postprocessor
from nonebot.matcher import Matcher
import random
from utils.QImage import *

sarcasm = on_command("嘲讽",priority=3)
welcom = on_notice(priority=4)
selfIntro = on_command("来点自我介绍",priority=4)
anonymous = on_command("隔空喊话",priority=3)
# poke = on_notice(priority=5)
# say = on_command("请说：",priority=3)
# red_true = on_regex("((#[0-9,a-f,A-F]{6})真实|(虚妄)真实|(红色)真实|(蓝色)真实|(金色)真实)：([\w\W]+)",priority=3)

@sarcasm.handle()
async def handle(bot: Bot, event: Event , msg:Message = CommandArg()):
    try:
        msg = re.findall("([\s\S]+)，([\s\S]+)",str(msg))[0]
        # print(msg)
        send_msg = f"仅凭借{msg[0]}，古户绘梨花便能{msg[1]}到这种程度，如何呀，诸位~"
        await sarcasm.finish(Message(send_msg))
    except:
        await sarcasm.finish()

@welcom.handle()
async def handle(bot: Bot, event: GroupIncreaseNoticeEvent ):
    user = event.get_user_id()
    at_ = "[CQ:at,qq={}]".format(user)
    # msg = at_+'新人，想学爆点吗？'
    msg = at_+'欢迎新宝宝进群~ 记得注意群公告哦！'
    await welcom.finish(Message(msg))

# @poke.handle()
# async def handle(bot: Bot, event: PokeNotifyEvent ):
#     msg = event.get_log_string()
#     check = re.search("'target_id': 2523899329",msg)
#     rsp = [f'[CQ:poke,type=1,id=-1,name="戳一戳",qq={event.get_user_id()}]'] #,'贱民也想戳一戳我？','再戳？']
#     if check:
#         await poke.finish(Message(random.choice(rsp)))
#     await poke.finish()

@selfIntro.handle()
async def handle(bot: Bot, event: Event , msg: Message = CommandArg()):
    await selfIntro.send(Message("初次见面，你好"))
    time.sleep(0.5)
    await selfIntro.send(Message("我的名字叫做 古户绘梨花"))
    time.sleep(0.5)
    await selfIntro.send(Message("虽然是位不速之客，还请多加欢迎"))
    time.sleep(0.5)
    await selfIntro.finish()


# @red_true.handle()
# async def handle(bot: Bot, event: Event ):
#     msg = state["_matched_groups"]
#     rgb_dirc = {'虚妄':'#ffffff','红色':'#ff6347','蓝色':'#7f00ff','金色':'#d9d919'}
#     color = rgb_dirc['虚妄']
#     for i in msg:
#         if i in ['虚妄','红色','蓝色','金色']:
#             color = rgb_dirc[i]
#             pass
#         elif i != None and i != msg[-1]:
#             color = i
#             pass
#     msg = msg[-1]
#     if event.get_user_id() not in ['1364374624','2450509502'] and color == '#d9d919':
#         await red_true.finish(Message('GameMaster岂是你能冒充的？'))
#     send_msg = [{'type':'xml','data':{}}]
#     data = f'''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><msg serviceID="1" templateID="-1" action="plugin" a_actionData="" brief="[真实]{msg}" sourceMsgId="0" url="" flag="2" adverSign="3" multiMsgFlag="0"><item layout="9" bg="2" advertiser_id="0" aid="0"><picture cover="https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_logo.png" w="0" h="0" /></item><item layout="6" advertiser_id="0" aid="0">
# <summary size="100" color="{color}">{msg}</summary></item><source name="" icon="" action="" appid="-1" /></msg>'''
#     send_msg[0]['data']['data'] = data
#     await red_true.finish(Message(send_msg))

# @say.handle()
# async def handle(bot: Bot, event: GroupMessageEvent,text: Message = CommandArg()):
#     text = re.findall('[\w\W]+',str(text))[0]
#     print("[!]tts语音接收字符长度：",len(text))
#     if len(text)<=100:
#         await say.finish(Message(f'[CQ:tts,text={text}]'))
#     else:
#         await say.finish(Message('你这个我说匿🐎！'))

@anonymous.handle()
async def handle(bot: Bot, event: Event , msg:Message = CommandArg()):
    # try:
    contect = re.findall("to ([0-9]+)[：]*([\s\S]*)",str(msg))[0]
    group = contect[0]
    if event.reply:
        msg = event.reply.message
    elif contect[1]:
        if contect[1][0] == '：':
            msg = contect[1][1:]
        else:
            msg = contect[1]
    else:
        await anonymous.finish()

    msg = str(msg)
    # if url := get_image_url(msg):
    #     if new_ana := cq_image_to(msg,url): #转换CQ格式修复图像显示
    #         msg = new_ana

    await bot.call_api('send_msg',**{
            'message':"吾主，收到【匿名消息】~",
            'group_id':int(group)
        })
    await bot.call_api('send_msg',**{
            'message':msg,
            'group_id':int(group)
        })
    await anonymous.finish()