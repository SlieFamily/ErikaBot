import nonebot
import re
import math
from .config import Config
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot,Event
from nonebot.params import ArgPlainText, Arg, CommandArg, RegexGroup, EventToMe
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER, PRIVATE_FRIEND
from nonebot.log import logger
from nonebot.message import run_postprocessor
from nonebot.matcher import Matcher
from nonebot_plugin_saa import MessageFactory, PlatformTarget, AggregatedMessageFactory
from nonebot_plugin_saa import TargetQQGroup, enable_auto_select_bot
from . import model
import random

# 初始化数据库
model.Init()

rsp = ["用最爱的筷子品味最恶俗的语录才称得上健全~","知性的强J者怎能输给后辈！"]

anas_rule = "([\w\W]{1,6}<高级>)语录|([\w\W]{1,6})语录"


# 默认配置
global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

# 响应命令
theirAna = on_regex("("+anas_rule+")[-]*([0-9]*)", priority=3) 
# AddAna = on_regex("add ("+anas_rule+")：([\s\S]+)", priority=2)
AddAna = on_command("add",priority=2)
DelAna = on_regex("del ("+anas_rule+")：([\s\S]+)",priority=2)
MergeAna = on_regex("merge ("+anas_rule+")，("+anas_rule+")",priority=1,permission=SUPERUSER)
LockAna = on_command("lock",priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER)
UnlockAna = on_command("unlock",priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER)
DelAllAna = on_command("drop",priority=1,permission=SUPERUSER)
Rename = on_regex("rename ("+anas_rule+") to ("+anas_rule+")",priority=1,permission=SUPERUSER)
FindAna = on_regex("find：([\s\S]+)",priority=1)
SuperAna = on_regex("[\w\W]+",priority=4)
AnaList = on_command("侦探的棋子名单",priority=3)
SuperList = on_command("侦探的魔女名单",priority=3)
abuse = on_regex("[\s\S]*",rule=to_me(),priority=6)
abuse_on = on_command("开启嘲讽状态",priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER)
abuse_off = on_command("关闭嘲讽状态",priority=1,permission=GROUP_ADMIN|GROUP_OWNER|PRIVATE_FRIEND|SUPERUSER)

enable_auto_select_bot() #为ssa插件自动获取bot

@AnaList.handle()
async def handle(bot: Bot, event: Event):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]

    names,cnts = model.GetList()
    msg = [] #合并聊天记录信息
    string = ""
    gp_names = []; gp_cnts = [] #每20条一页
    for i in range(0,len(names),20):
        gp_names.append(names[i:i+20])
        gp_cnts.append(cnts[i:i+20])

    for k in range(math.ceil(len(names)/20)):    
        for i in range(len(gp_names[k])):
            string += gp_names[k][i]+'语录 \t('+ str(gp_cnts[k][i]) +'条)\n'
        msg.append(MessageFactory(string[:-1]))
        string = ""

    await AggregatedMessageFactory(msg).send_to(TargetQQGroup(group_id=group))
    await AnaList.finish()

@SuperList.handle()
async def handle(bot: Bot,event: Event ):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]

    names,cnts = model.GetSuperList()
    msg = [] #合并聊天记录信息
    string = ""
    gp_names = []; gp_cnts = [] #每20条一页
    for i in range(0,len(names),20):
        gp_names.append(names[i:i+20])
        gp_cnts.append(cnts[i:i+20])

    for k in range(math.ceil(len(names)/20)):    
        for i in range(len(gp_names[k])):
            string += gp_names[k][i][:-4]+' \t('+ str(gp_cnts[k][i]) +'条)\n'
        msg.append(MessageFactory(string[:-1]))
        print(string)
        string = ""

    await AggregatedMessageFactory(msg).send_to(TargetQQGroup(group_id=group))
    await AnaList.finish()

@theirAna.handle()
async def handle(bot: Bot, event: Event, name = RegexGroup()):
    num = name[3]
    name = name[1] if name[1] else name[2]
    group = event.get_session_id()
    my_ana = ''
    if not group.isdigit():
        group = group.split('_')[1]
    if not num:
        my_ana = model.GetAna(name,group) #获取随机语录
    else:
        try:
           my_ana = model.GetAna(name,group,int(num)) #获取指定序号的语录
    # state["auto_name"] = name
    # AutoAna = Matcher.new(temp=True,priority=4,default_state=state)
    # @AutoAna.handle()
    # async def handle(bot: Bot, event: Event, state: T_State):
    #     try:
    #         ana = event.get_message()
    #         if event.get_user_id() == "2450509502" and name != "爆点":
    #             res = re.findall(",url=([a-zA-z]+://[^\s]*)[,]*\]",ana)
    #             if res:
    #                 ana = re.sub("\[CQ:image,[\w\W]+,url=[a-zA-z]+://[^\s]*[,]*[\w\W]*\]","[CQ:image,file="+res[0]+"]",ana)
    #             if model.IsAdded(state["auto_name"],ana,"Auto"):
    #                 # await AutoAna.finish(Message(random.choice(rsp)))
    #                 pass
        except:
            pass
    if my_ana:
        await theirAna.finish(Message(my_ana))
    await theirAna.finish() 

@AddAna.handle()
async def handle(bot: Bot, event: Event , args: Message = CommandArg()):
    if msg := args.extract_plain_text():
        name = re.findall("("+anas_rule+")[:]*([\s\S]*)",str(msg))[0]
        ana = name[3][1:]
        by = event.get_user_id()
        name = name[1] if name[1] else name[2]
        if event.reply:
            ana = event.reply.message
            if model.IsAdded(name,ana,by):
                await AddAna.finish(Message(random.choice(rsp)))
        elif ana:
            if model.IsAdded(name,ana,by):
                await AddAna.finish(Message(random.choice(rsp)))
        await AddAna.finish(Message("苦撸西，失败了失败了！"))
    else:
        await AddAna.finish()
    


@DelAna.handle()
async def handle(bot: Bot,event: Event ,name = RegexGroup()):
    ana = name[3]
    name = name[1] if name[1] else name[2]
    del_msg = model.IsDel(name,ana)
    if del_msg:
        await DelAna.finish(Message("这种垃圾语录没有存在的必要！"))
    await DelAna.finish(Message("失败了失败了失败了……"))

@MergeAna.handle()
async def handle(bot: Bot,event: Event ,name = RegexGroup()):
    name1 = name[1] if name[1] else name[2]
    name2 = name[4] if name[4] else name[5]
    flag = model.Merge(name1,name2)
    if flag:
        await MergeAna.finish(Message("语录合并成功，多余的棋子就应该抛弃，是吧嘉音！"))
    await MergeAna.finish(Message("家具就是家具，无法成为人！"))

@LockAna.handle()
async def handle(bot: Bot,event: Event , name: Message = CommandArg()):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    name = re.findall("([\w\W]+)语录",str(name))[0]
    flag = model.SetLock(name,group)
    if flag:
        await LockAna.finish(Message(f"本群已限制访问{name}语录~"))
    await LockAna.finish(Message("禁止访问失败~"))

@UnlockAna.handle()
async def handle(bot: Bot,event: Event  ,name: Message = CommandArg()):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    name = re.findall("([\w\W]+)语录",str(name))[0]
    flag = model.SetUnlock(name,group)
    if flag:
        await UnlockAna.finish(Message(f"本群访问{name}语录限制解除~"))
    await UnlockAna.finish(Message("解除访问失败~"))

@DelAllAna.handle()
async def handle(bot: Bot,event: Event , name: Message = CommandArg()):
    name = re.findall("([\w\W]+)语录",str(name))[0]
    flag = model.DropAna(name)
    if flag:
        await DelAllAna.finish(Message(f"果然{name}语录，就是应该狼狈退场呢~"))
    await DelAllAna.finish(Message("嘁，让他侥幸存活了"))

@FindAna.handle()
async def handle(bot: Bot, event: Event ,ana = RegexGroup()):
    ana = ana[0]
    infs = model.Inf(ana)
    if infs:
        msg = f"发现{len(infs)}条相关语录\n\n"
        for i in range(len(infs)):
            msg += f"第{i+1}条：\n"
            msg += f'来自：{infs[i][0]}语录\n'
            msg += f'添加者(QQ)：{infs[i][2]}\n'
            msg += '内容：\n'+infs[i][1]
            if i < len(infs)-1:
                msg += '\n\n'
        await FindAna.send(Message(msg))
    await FindAna.finish()

@abuse.handle()
async def handle(bot: Bot, event: GroupMessageEvent,at_me=EventToMe() ):
    name = "Erika"
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    my_ana = model.GetAna(name,group)
    if my_ana and at_me:
        await abuse.finish(Message(my_ana))
    await abuse.finish()

@abuse_off.handle()
async def handle(bot: Bot, event: Event ):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    name = "Erika"
    flag = model.SetLock(name,group)
    if flag:
        await abuse_off.finish(Message('已关闭嘲讽状态，你再怎么@我，你看我理你吗？'))
    else:
        await abuse_off.finish()

@abuse_on.handle()
async def handle(bot: Bot, event: Event ):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    name = "Erika"
    flag = model.SetUnlock(name,group)
    if flag:
        await abuse_on.finish(Message('已成功开启嘲讽状态，试试@我一下吧~'))
    else:
        await abuse_on.finish()

@SuperAna.handle()
async def handle(bot: Bot, event: Event ):
    name = re.findall(model.GetReRule(),str(event.get_message()))
    if not name:
        await SuperAna.finish()
    name = name[0]+"<高级>"
    isSelf = re.findall("'nickname': '古都艾丽卡'",str(event.get_log_string()))
    if isSelf:
        await SuperAna.finish()
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    ana = model.GetAna(name,group)
    if ana:
        await SuperAna.finish(Message(ana))
    await SuperAna.finish()

@Rename.handle()
async def handle(bot: Bot, event: Event ,name = RegexGroup()):
    print(name)
    name1 = name[1] if name[1] else name[2]
    name2 = name[4] if name[4] else name[5]
    if model.RenameAna(name1,name2):
        await Rename.finish(Message("*进行Psync成功*"))
    await Rename.finish(Message("还是好好呆着吧~"))
