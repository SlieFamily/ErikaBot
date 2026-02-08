from dataclasses import MISSING
from nonebot import on_command
from nonebot import rule
from nonebot import on_request
from nonebot import on_notice
from nonebot.adapters import Bot,Event
from nonebot.params import ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent,GroupMessageEvent
from nonebot.adapters.onebot.v11.event import MessageEvent, Status
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER, PRIVATE_FRIEND
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11 import Bot,Message,GroupMessageEvent,bot,FriendRequestEvent,GroupRequestEvent,GroupDecreaseNoticeEvent
from nonebot_plugin_saa import MessageFactory, PlatformTarget, AggregatedMessageFactory
from nonebot_plugin_saa import TargetQQGroup, enable_auto_select_bot, Image, Text
from nonebot import require
from nonebot.log import logger
from . import rss_tool
from . import biliLive, biliDynamic
from . import RSS
from . import config
import asyncio
import nonebot
import threading

enable_auto_select_bot() #为ssa插件自动获取bot

RSS.Init2db() #数据库初始化

index = 0 #用于轮流刷新

# 请求定时任务对象scheduler   
scheduler = require('nonebot_plugin_apscheduler').scheduler

# 创建定时任务：推送订阅信息/每5min查询一次
@scheduler.scheduled_job('interval', seconds = 20, id = 'update') #minutes = 1
async def update():
    
    if RSS.Empty():
        return #数据库关注列表为空，无事发生

    global index
    users = RSS.GetUserList()
    index %= len(users) #当idx值超过用户数时，idx的值轮换到下一周期
    app = users[index][0]
    name = users[index][1]
    user_id = users[index][2]
    msg_id = users[index][3]
    url = users[index][4]
    logger.info(f'[!]查询 {app}:{name}({user_id}) 动态……')
    if app == 'bili直播':
        new_msg_id, datas = await biliLive.get_latest_datas(user_id)
        if new_msg_id == '0' or msg_id == '1': #直播未开播或已发送开播提醒
            RSS.UpdateMsg(user_id, new_msg_id) #更新数据库的最新 msg_id
            index += 1
            return #未开播或获取信息失败
    elif app == 'B站':
        new_msg_id, datas = await biliDynamic.get_latest_datas(user_id) 
        if new_msg_id == msg_id:
            index += 1
            return #最新 msg_id 和上次收录的一致(说明并未更新)
    else:
        new_msg_id, datas = await rss_tool.get_latest_datas(url)

    logger.info(f'[!]检测到 {app}:{name} 已更新')
    RSS.UpdateMsg(user_id, new_msg_id) #更新数据库的最新 msg_id
    if app == 'bili直播':
        msgs = await biliLive.get_Qmsg(name, datas, msg_id) #读取信息详情
    elif app == 'B站':
        msgs = await biliDynamic.get_Qmsg(name, datas, msg_id)
    else:
        msgs = await rss_tool.get_Qmsg(name, datas, msg_id)

    cards = RSS.GetALLCard(user_id) #card: [group_id(s), is_translate(s)]
    schedBot = nonebot.get_bot()

    media = ""
    msg, imgs, time = msgs
    for img in imgs:
        print(img)
        media += f"[CQ:image,file={img}]"
    for card in cards:
        await schedBot.call_api('send_msg',**{
                'message':msg+media+"\n🔔："+time,
                'group_id':card[0]
        })
    index += 1
    
# 关注命令(仅允许管理员操作)
adduser = on_command('关注',priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@adduser.handle()
async def handle(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = event.get_session_id()
    if not group_id.isdigit():
        group_id = group_id.split('_')[1] #获取群聊号

    msg = '命令格式 Error 哒~ 吾主！'
    
    if args != '':

        try:
            app,user_id = str(args).split("：")
        except:
            await adduser.finish(Message(msg))
        user_inf = RSS.GetUserInfo(user_id)# 如果该用户已存在数据库中，直接拉取
        if len(user_inf) != 0:
                status = RSS.AddCard(user_id, group_id)
                if status == 0:
                    msg = f'吾主，{user_inf[0]}({user_id})已经关注成功！'
                else:
                    msg = f'{user_inf[0]}({user_id})棋子早已就绪！'
        else: #否则联网获取信息
            data = RSS.LoadRssRule()
            url = data['route'][app]+user_id
            if app == 'bili直播':
                screen_name = await biliLive.get_user_info(user_id)
            elif app == 'B站':
                screen_name = await biliDynamic.get_user_info(user_id)
            else:
                screen_name = await rss_tool.get_user_info(url)
            if (screen_name != ''):
                RSS.AddUser(app, user_id, screen_name)
                RSS.AddCard(user_id, group_id)
                msg = f'吾主，{screen_name}({user_id})已经关注成功！'
            else:
                msg = f'{user_id} 不存在或网络错误！'
    await adduser.finish(Message(msg))

#取关用户(仅允许管理员操作)    
removeuser = on_command('取关',priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@removeuser.handle()
async def handle(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    group_id = event.get_session_id()
    if not group_id.isdigit():
        group_id = group_id.split('_')[1] #获取群聊号

    msg = '命令格式 Error 哒~ 吾主！'

    if args != '':
        user_id = args
        user_inf = RSS.GetUserInfo(user_id)
        if len(user_inf) == 0:
            msg = f'吾主，{user_id} 这样的棋子，好……好像不存在！'
        else:
            status = RSS.DeleteCard(user_id,group_id)
            if status != 0:
                msg = f'吾主，{user_inf[0]}({user_id})不在本群的关注列表'
            else:
                msg = f'{user_inf[0]}({user_id})删除成功！'
    await adduser.finish(Message(msg))

#显示本群中的关注列表(仅允许管理员操作)  
alllist = on_command('关注列表',priority=1)
@alllist.handle()
async def handle(bot: Bot, event: GroupMessageEvent):
    group_id = event.get_session_id()
    if not group_id.isdigit():
        group_id = group_id.split('_')[1] #获取群聊号

    msg = '应用-用户名(ID)\n'
    content = ''
    users = RSS.GetUserList()
    for user in users:
        card = RSS.GetCard(user[2],group_id)
        if len(card) != 0:
            content += f'\n{user[0]}-{user[1]}({user[2]})'
    if content == '':
        msg = '当前关注列表为空！'
    else:
        msg = msg + content

    await alllist.finish(Message(msg))


# 退群后自动删除该群关注信息
group_decrease = on_notice(priority=5)
@group_decrease.handle()
async def _(bot: Bot, event: GroupDecreaseNoticeEvent):
    group_id = event.get_session_id()
    if not group_id.isdigit():
        group_id = group_id.split('_')[1] #获取群聊号

    if event.self_id == event.user_id:
        RSS.DeleteGroupCard(group_id)

# #开启推文翻译(仅允许管理员操作)
# ontranslate = on_command('开启翻译',rule=to_me(),priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
# @ontranslate.handle()
# async def handle(bot: Bot, event: GroupMessageEvent, state: T_State = State()):
#     group_id = event.get_session_id()
#     if not group_id.isdigit():
#         group_id = group_id.split('_')[1] #获取群聊号

#     args = str(event.get_message()).strip()
#     msg = '指令格式错误！请按照：开启翻译 推特ID'
#     if args != '':
#         user = RSS.GetUserInfo(args)
#         if len(user) == 0:
#             msg = '{} 用户不存在！请检查UID是否错误'.format(args)
#         else:
#             card=RSS.GetCard(args,id,is_group)
#             if len(card)==0:
#                 msg = '{}({})不在当前关注列表！'.format(user[1],args)
#             else:
#                 RSS.TranslateON(args,id,is_group)
#                 msg = '{}({})开启推文翻译！'.format(user[1],args)
#     Msg = Message(msg)
#     await ontranslate.finish(Msg)

# #关闭推文翻译(仅允许管理员操作)
# offtranslate = on_command('关闭翻译',rule=to_me(),priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
# @offtranslate.handle()
# async def handle(bot: Bot, event: GroupMessageEvent, state: T_State = State()):
#     group_id = event.get_session_id()
#     if not group_id.isdigit():
#         group_id = group_id.split('_')[1] #获取群聊号

#     args = str(event.get_message()).strip()
#     msg = '指令格式错误！请按照：关闭翻译 推特ID'
#     if args!='':
#         user=RSS.GetUserInfo(args)
#         if len(user)==0:
#             msg = '{} 用户不存在！请检查UID是否错误'.format(args)
#         else:
#             card=RSS.GetCard(args,id,is_group)
#             if len(card)==0:
#                 msg='{}({})不在当前群组/私聊关注列表！'.format(user[1],args)
#             else:
#                 RSS.TranslateOFF(args,id,is_group)
#                 msg='{}({})关闭推文翻译！'.format(user[1],args)
#     Msg=Message(msg)
#     await offtranslate.finish(Msg)