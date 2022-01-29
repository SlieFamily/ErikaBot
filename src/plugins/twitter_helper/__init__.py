from dataclasses import MISSING
from nonebot import on_command
from nonebot import rule
from nonebot import on_request
from nonebot import on_notice
from nonebot.adapters import Bot,Event
from nonebot.adapters.cqhttp.event import MessageEvent, Status
from nonebot.rule import to_me
from nonebot.adapters.cqhttp.permission import GROUP_ADMIN, GROUP_OWNER, PRIVATE_FRIEND
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot.adapters.cqhttp import Bot,Message,GroupMessageEvent,bot,FriendRequestEvent,GroupRequestEvent,GroupDecreaseNoticeEvent
from nonebot.adapters.cqhttp.message import MessageSegment
from nonebot_plugin_guild_patch import GuildMessageEvent
from nonebot import require
from nonebot.log import logger
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from . import data_source
from . import model
from . import config
import asyncio
import nonebot
import threading

model.Init() #数据库初始化

config.token = data_source.init() #token获取初始化

tweet_index = 0

# 更新token操作函数
def flush_token():
    chrome_options = Options()
    chrome_options.add_argument('--no-sandbox')#解决DevToolsActivePort文件不存在的报错
    chrome_options.add_argument('window-size=1920x3000') #指定浏览器分辨率
    chrome_options.add_argument('--disable-gpu') #谷歌文档提到需要加上这个属性来规避bug
    chrome_options.add_argument('--hide-scrollbars') #隐藏滚动条, 应对一些特殊页面
    chrome_options.add_argument('blink-settings=imagesEnabled=false') #不加载图片, 提升速度
    chrome_options.add_argument('--headless') #浏览器不提供可视化页面. linux下如果系统不支持可视化不加这条会启动失败
    driver = webdriver.Chrome(options=chrome_options)
    driver.delete_all_cookies()
    try:
        driver.get('https://mobile.twitter.com/Twitter')
        driver.execute_script("window.scrollTo(0,document.body.scrollHeight)")
        time.sleep(10)
    except:
        logger.error('twitter.com请求超时！')
        driver.execute_script("window.stop()")
    data = driver.get_cookie('gt') 
    driver.close()
    driver.quit()
    if data == None:
        logger.error('token初始化失败，请检查网络设置或API地址是否正确！')
        return
    config.token = data['value']

# 请求定时任务对象scheduler   
scheduler = require('nonebot_plugin_apscheduler').scheduler

# 创建定时任务：刷新token/每5min更新一次 
@scheduler.scheduled_job('interval',minutes=5,id='flush_token',timezone='Asia/Shanghai')
async def flush():
    flush = threading.Thread(target=flush_token)
    flush.start()
    logger.info('开始刷新token')

# 创建定时任务：推送tweet/每15s查询一次
@scheduler.scheduled_job('interval',seconds=15,id='tweet')
async def tweet():
    if model.Empty():
        return #数据库关注列表为空，无事发生
    (schedBot,) = nonebot.get_bots().values()
    global tweet_index
    users = model.GetUserList()
    tweet_index %= len(users) #注意
    tweet_id,data = await data_source.get_latest_tweet(users[tweet_index][2],config.token)
    if tweet_id == '' or users[tweet_index][3] == tweet_id:
        tweet_index += 1
        return #最新推文id和上次收录的一致(说明并未更新)
    logger.info('检测到 %s 的推特已更新'%(users[tweet_index][1]))
    model.UpdateTweet(users[tweet_index][0],tweet_id) #更新数据库的最新推文id
    text,translate,media_list,retweet_name=data_source.get_tweet_details(data) #读取tweet详情
    translate=await data_source.baidu_translate(config.appid,translate,config.baidu_token) #翻译
    media = ''
    for item in media_list:
        media += MessageSegment.image(item)+'\n'
    cards = model.GetALLCard(users[tweet_index][0])
    for card in cards:
        if card[1] == 1:#是群聊
            if model.IsNotInCard(retweet_name,card[0]): #如果是转推，已经推送过则不再推送
                if card[2] == 1:#需要翻译
                    await schedBot.call_api('send_msg',**{
                        'message':text+translate+media,
                            'group_id':card[0]
                    })
                else:#不需要翻译
                    await schedBot.call_api('send_msg',**{
                            'message':text+media,
                            'group_id':card[0]
                    })
            else:
                logger.info(f'QQ群({card[0]})重复推文过滤')
        else:#私聊
            if model.IsNotInCard(retweet_name,card[0]):
                if card[2] == 1:#需要翻译
                    await schedBot.call_api('send_msg',**{
                        'message':text+translate+media,
                        'user_id':card[0]
                    })
                else:
                    await schedBot.call_api('send_msg',**{
                        'message':text+media,
                        'user_id':card[0]
                    })
            else:
                logger.info(f'QQ群({card[0]})重复推文过滤')
    await schedBot.call_api("send_guild_channel_msg",**{
        'guild_id':54880161636523193,
        'channel_id':2841279,
        'message':text+media
        })
    tweet_index += 1
    
# 关注推特命令(仅允许管理员操作)
adduser = on_command('给爷关注',rule=to_me(),priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@adduser.handle()
async def handle(bot: Bot, event: MessageEvent, state: T_State):
    is_group = int(isinstance(event,GroupMessageEvent))
    id = event.get_session_id()
    if not id.isdigit():
        id = id.split('_')[1]
    args = str(event.get_message()).strip()
    msg = '命令格式Error哒，吾主！'
    if args!='':
        user = model.GetUserInfo(args)# 如果该用户已存在数据库中，直接拉取
        if len(user) != 0:
                status = model.AddCard(args,id,is_group)
                if status == 0:
                    msg='吾主，{}({})已经关注成功！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_ok.jpeg]'.format(user[1],args) #待测试
                else:
                    msg='{}({})棋子早已就绪！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_ok.jpeg]'.format(user[1],args) #待测试
        else: #否则联网获取信息
            user_name,user_id = await data_source.get_user_info(args,config.token)
            if(user_id != ''):
                model.AddNewUser(args,user_name,user_id)
                model.AddCard(args,id,is_group)
                msg = '吾主，{}({})已经关注成功！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/erika_ok.jpeg]'.format(user_name,args) #待测试
            else:
                msg = '{} 推特ID不存在或网络错误！\n'.format(args)
    Msg = Message(msg)
    await adduser.finish(Msg)

#取关用户(仅允许管理员操作)    
removeuser = on_command('取关',rule=to_me(),priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@removeuser.handle()
async def handle(bot: Bot, event: MessageEvent, state: T_State):
    is_group = int(isinstance(event,GroupMessageEvent))
    id = event.get_session_id() #注意
    if not id.isdigit():
        id = id.split('_')[1]
    args = str(event.get_message()).strip()
    msg = '命令格式Error哒，吾主'
    if args != '':
        user=model.GetUserInfo(args)
        if len(user) == 0:
            msg = '吾主，{} 这样的棋子，好……好像不存在！'.format(args)
        else:
            status = model.DeleteCard(args,id,is_group)
            if status != 0:
                msg = '吾主，{}({})不在本群的关注列表'.format(user[1],args)
            else:
                msg = '{}({})删除成功！\n[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main/Auto/erika_ok.jpeg]'.format(user[1],args)
    Msg = Message(msg)
    await adduser.finish(Msg)

#显示本群中的关注列表(仅允许管理员操作)  
alllist = on_command('关注列表',priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@alllist.handle()
async def handle(bot: Bot, event: MessageEvent, state: T_State):
    is_group = int(isinstance(event,GroupMessageEvent))
    id = event.get_session_id()
    if not id.isdigit():
        id = id.split('_')[1]
    msg = '用户名(推特ID)\n'
    content = ''
    if not id.isdigit():
        id = id.split('_')[1]
    user = model.GetUserList()
    for index in user:
        card = model.GetCard(index[0],id,is_group)
        if len(card) != 0:
            content += '{}({})\n'.format(index[1],index[0])
    if content == '':
        msg = '当前关注列表为空！'
    else:
        msg = msg + content
    Msg = Message(msg)
    await alllist.finish(Msg)

#开启推文翻译(仅允许管理员操作)
ontranslate = on_command('开启翻译',rule=to_me(),priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@ontranslate.handle()
async def handle(bot: Bot, event: MessageEvent, state: T_State):
    is_group=int(isinstance(event,GroupMessageEvent))
    id=event.get_session_id()
    if not id.isdigit():
        id=id.split('_')[1]
    args = str(event.get_message()).strip()
    msg = '指令格式错误！请按照：开启翻译 推特ID'
    if args != '':
        user = model.GetUserInfo(args)
        if len(user) == 0:
            msg = '{} 用户不存在！请检查UID是否错误'.format(args)
        else:
            card=model.GetCard(args,id,is_group)
            if len(card)==0:
                msg = '{}({})不在当前关注列表！'.format(user[1],args)
            else:
                model.TranslateON(args,id,is_group)
                msg = '{}({})开启推文翻译！'.format(user[1],args)
    Msg = Message(msg)
    await ontranslate.finish(Msg)

#关闭推文翻译(仅允许管理员操作)
offtranslate = on_command('关闭翻译',rule=to_me(),priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER,)
@offtranslate.handle()
async def handle(bot: Bot, event: MessageEvent, state: T_State):
    is_group=int(isinstance(event,GroupMessageEvent))
    id=event.get_session_id()
    if not id.isdigit():
        id=id.split('_')[1]
    args = str(event.get_message()).strip()
    msg = '指令格式错误！请按照：关闭翻译 推特ID'
    if args!='':
        user=model.GetUserInfo(args)
        if len(user)==0:
            msg = '{} 用户不存在！请检查UID是否错误'.format(args)
        else:
            card=model.GetCard(args,id,is_group)
            if len(card)==0:
                msg='{}({})不在当前群组/私聊关注列表！'.format(user[1],args)
            else:
                model.TranslateOFF(args,id,is_group)
                msg='{}({})关闭推文翻译！'.format(user[1],args)
    Msg=Message(msg)
    await offtranslate.finish(Msg)

#帮助
help = on_command('twitter帮助',priority=1)
@help.handle()
async def handle(bot: Bot, event: MessageEvent, state: T_State):
    menu='绘梨花twitter小助手 目前支持的功能：\n(请将ID替换为需操作的推特ID，即@后面的名称)\n给爷关注 ID\n取关 ID\n关注列表\n开启翻译 ID\n关闭翻译 ID\n'
    info='当前版本：v1.04\n作者：Slie\n原作：鹿乃ちゃんの猫'
    msg=menu+info
    Msg=Message(msg)
    await help.finish(Msg)

# 退群后自动删除该群关注信息
group_decrease = on_notice(priority=5)
@group_decrease.handle()
async def _(bot: Bot, event: GroupDecreaseNoticeEvent, state: T_State):
    id=event.get_session_id()
    if not id.isdigit():
        id=id.split('_')[1]
    if event.self_id == event.user_id:
        model.DeleteGroupCard(id)