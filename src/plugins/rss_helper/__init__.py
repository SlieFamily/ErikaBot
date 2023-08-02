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
from nonebot_plugin_guild_patch import GuildMessageEvent
from nonebot import require
from nonebot.log import logger
from . import rss_tool
from . import RSS
from . import config
import asyncio
import nonebot
import threading

RSS.Init2db() #数据库初始化

index = 0 #用于轮流刷新

# 请求定时任务对象scheduler   
scheduler = require('nonebot_plugin_apscheduler').scheduler

# 创建定时任务：推送订阅信息/每1min查询一次
@scheduler.scheduled_job('interval',minutes = 1,id = 'update')
async def update():
    
    if RSS.Empty():
        return #数据库关注列表为空，无事发生

    global index
    users = RSS.GetUserList()
    index %= len(users) #当idx值超过用户数时，idx的值轮换到下一周期
    name = users[index][0]
    user_id = users[index][1]
    msg_id = users[index][2]
    url = users[index][3]
    logger.info(f'[!]查询 {name} 的推特……')
    new_msg_id,data = await rss_tool.get_latest_msg(url)
    if new_msg_id == '' or new_msg_id == msg_id:
        index += 1
        return #最新 msg_id 和上次收录的一致(说明并未更新) 或 获取信息失败

    logger.info(f'[!]检测到 {name} 已更新')
    RSS.UpdateMsg(user_id, new_msg_id) #更新数据库的最新 msg_id
    is_translate = False
    msg,imgs = await rss_tool.get_Qmsg(name,data) #读取信息详情

    media = ''
    for item in imgs:
        media += MessageSegment.image(item)+'\n'

    cards = RSS.GetALLCard(user_id) #card: [group_id(s), is_translate(s)]

    schedBot = nonebot.get_bot()
    for card in cards:
        if card[1] == '1':#需要翻译
            await schedBot.call_api('send_msg',**{
                'message':msg+"-----[翻译]-----\n"+baidu_translate(msg)+media,
                    'group_id':card[0]
            })
        else:#不需要翻译
            await schedBot.call_api('send_msg',**{
                    'message':msg+media,
                    'group_id':card[0]
            })

    # await schedBot.call_api("send_guild_channel_msg",**{
    #     'guild_id':54880161636523193,
    #     'channel_id':2841279,
    #     'message':msg+media
    #     })
    # await schedBot.call_api("send_guild_channel_msg",**{
    #     'guild_id':28505721637064109,
    #     'channel_id':2871978,
    #     'message':msg+media
    #     })
    index += 1
    
# 关注推特命令(仅允许管理员操作)
adduser = on_command('验尸',priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
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
                status = RSS.AddCard(user_id,group_id)
                if status == 0:
                    msg = f'吾主，{user_inf[0]}({user_id})已经关注成功！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_ok.jpeg]'
                else:
                    msg = f'{user_inf[0]}({user_id})棋子早已就绪！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_ok.jpeg]'
        else: #否则联网获取信息
            url = RSS.rss_url+RSS.Apps2Url[app]+user_id
            screen_name = await rss_tool.get_user_info(url)
            if (screen_name != ''):
                RSS.AddUser(app, user_id, screen_name)
                RSS.AddCard(user_id, group_id)
                msg = f'吾主，{screen_name}({user_id})已经关注成功！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_ok.jpeg]'
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
                msg = f'{user_inf[0]}({user_id})删除成功！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main/Auto/erika_ok.jpeg]'
    await adduser.finish(Message(msg))

#显示本群中的关注列表(仅允许管理员操作)  
alllist = on_command('完美验尸表',priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@alllist.handle()
async def handle(bot: Bot, event: GroupMessageEvent):
    group_id = event.get_session_id()
    if not group_id.isdigit():
        group_id = group_id.split('_')[1] #获取群聊号

    msg = '用户名(订阅号ID)\n'
    content = ''
    users = RSS.GetUserList()
    for user in users:
        card = RSS.GetCard(user[1],group_id)
        if len(card) != 0:
            content += f'\n{user[0]}({user[1]})'
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