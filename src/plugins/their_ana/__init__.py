import nonebot
import re
from .config import Config
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot,Event
from nonebot.adapters.cqhttp import Message,MessageSegment,GroupIncreaseNoticeEvent,GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.adapters.cqhttp.permission import GROUP_ADMIN, GROUP_OWNER, PRIVATE_FRIEND
from nonebot.log import logger
from nonebot.message import run_postprocessor
from nonebot.matcher import Matcher
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
theirAna = on_regex("("+anas_rule+")", priority=3) 
AddAna = on_regex("add ("+anas_rule+")：([\s\S]+)", priority=2)
Addabuse = on_regex("add Erika嘴臭：([\s\S]+)", priority=2)
DelAna = on_regex("del ([\w\W]+)语录：([\s\S]+)",priority=2)
Delabuse = on_regex("del Erika嘴臭：([\s\S]+)", priority=2)
MergeAna = on_regex("merge ("+anas_rule+")，("+anas_rule+")",priority=1,permission=SUPERUSER)
LockAna = on_command("lock",priority=1,permission=SUPERUSER)
UnlockAna = on_command("unlock",priority=1,permission=SUPERUSER)
DelAllAna = on_command("drop",priority=1,permission=SUPERUSER)
FindAna = on_regex("find：([\s\S]+)",priority=1)
SuperAna = on_regex("[\w\W]+",priority=5)

AnaList = on_command("语录清单",priority=3)
abuse = on_regex("[\s\S]*",rule=to_me(),priority=5)
say = on_command("请说：",priority=3)

@AnaList.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    names = model.GetList()
    msg = ''
    for name in names:
        msg += name+'\n'
    if msg:
        await AnaList.finish(Message(msg))
    else:
        await AnaList.finish()

@theirAna.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    name = state["_matched_groups"]
    name = name[1] if name[1] else name[2]
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    my_ana = model.GetAna(name,group) #获取随机语录
    state["auto_name"] = name
    AutoAna = Matcher.new(temp=True,priority=4,default_state=state)
    @AutoAna.handle()
    async def handle(bot: Bot, event: Event, state: T_State):
        try:
            ana = event.get_message()
            if event.get_user_id() == "2450509502" and name != "爆点":
                res = re.findall(",url=([a-zA-z]+://[^\s]*)[,]*\]",ana)
                if res:
                    ana = re.sub("\[CQ:image,[\w\W]+,url=[a-zA-z]+://[^\s]*[,]*[\w\W]*\]","[CQ:image,file="+res[0]+"]",ana)
                if model.IsAdded(state["auto_name"],ana,"Auto"):
                    # await AutoAna.finish(Message(random.choice(rsp)))
                    pass
        except:
            pass
    if my_ana:
        await theirAna.finish(Message(my_ana))
    await theirAna.finish() 

@AddAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    name = state["_matched_groups"]
    name = name[1] if name[1] else name[2]
    ana = state["_matched_groups"][3]
    res = re.findall(",url=([a-zA-z]+://[^\s]*)[,]*\]",ana)
    if res:
        ana = re.sub("\[CQ:image,[\w\W]+,url=[a-zA-z]+://[^\s]*[,]*[\w\W]*\]","[CQ:image,file="+res[0]+"]",ana)
    by = event.get_user_id()
    if model.IsAdded(name,ana,by):
        await AddAna.finish(Message(random.choice(rsp)))
    await AddAna.finish(Message("苦撸西，失败了失败了！"))

@Addabuse.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    ana = state["_matched_groups"][0]
    by = event.get_user_id()
    if model.IsAdded("Erika",ana,by):
        await AddAna.finish(Message(random.choice(rsp)))
    await AddAna.finish(Message("苦撸西，失败了失败了！"))

@DelAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    name = state["_matched_groups"][0]
    ana = state["_matched_groups"][1]
    del_msg = model.IsDel(name,ana)
    if del_msg:
        await DelAna.finish(Message("这种垃圾语录没有存在的必要！"))
    await DelAna.finish(Message("失败了失败了失败了……"))

@Delabuse.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    ana = state["_matched_groups"][0]
    del_msg = model.IsDel("Erika",ana)
    if del_msg:
        await DelAna.finish(Message("本来还能继续骂的"))
    await DelAna.finish(Message("失败了失败了失败了……"))

@MergeAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    name1 = state["_matched_groups"]
    name1 = name1[1] if name1[1] else name1[2]
    name2 = state["_matched_groups"]
    name2 = name2[4] if name2[4] else name2[5]
    print(name1,name2)
    flag = model.Merge(name1,name2)
    if flag:
        await MergeAna.finish(Message("语录合并成功，多余的棋子就应该抛弃，是吧嘉音！"))
    await MergeAna.finish(Message("家具就是家具，无法成为人！"))

@LockAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    state["group"] = group
    name = str(event.get_message()).strip()
    if name:
        state["name"] = name

@LockAna.got("name", prompt="该限制什么语录呢？")
async def got_name(bot: Bot,event: Event, state: T_State):
    name = re.findall("to ([\w\W]+)语录",state["name"])[0]
    flag = model.SetLock(name,state["group"])
    if flag:
        await LockAna.finish(Message(f"本群已限制访问{name}语录~"))
    await LockAna.finish(Message("禁止访问失败~"))

@UnlockAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    state["group"] = group
    name = str(event.get_message()).strip()
    if name:
        state["name"] = name

@UnlockAna.got("name", prompt="该解除什么语录呢？")
async def got_name(bot: Bot,event: Event, state: T_State):
    name = re.findall("to ([\w\W]+)语录",state["name"])[0]
    flag = model.SetUnlock(name,state["group"])
    if flag:
        await UnlockAna.finish(Message(f"本群访问{name}语录限制解除~"))
    await UnlockAna.finish(Message("解除访问失败~"))

@DelAllAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    state["group"] = group
    name = str(event.get_message()).strip()
    if name:
        state["name"] = name

@DelAllAna.got("name", prompt="啊~全都要摧毁！全都要！")
async def got_name(bot: Bot,event: Event, state: T_State):
    name = re.findall("([\w\W]+)语录",state["name"])[0]
    flag = model.DropAna(name)
    if flag:
        await DelAllAna.finish(Message(f"果然{name}语录，就是应该狼狈退场呢~"))
    await DelAllAna.finish(Message("嘁，让他侥幸存活了"))

@FindAna.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    ana = state["_matched_groups"][0]
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
async def handle(bot: Bot, event: GroupMessageEvent, state: T_State):
    name = "Erika"
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    my_ana = model.GetAna(name,group)
    if my_ana:
        await abuse.finish(Message(my_ana))
    await abuse.finish()

@SuperAna.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    name = re.findall(model.GetReRule(),str(event.get_message()))
    if not name:
        await SuperAna.finish()
    name = name[0]+"<高级>"
    isSelf = re.findall("\'user_id\': 144115218677564699",str(event.get_log_string()))
    if isSelf:
        await SuperAna.finish()
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    ana = model.GetAna(name,group)
    if ana:
        await SuperAna.finish(Message(ana))
    await SuperAna.finish()

@say.handle()
async def handle(bot: Bot, event: GroupMessageEvent, state: T_State):
    # msg_id = re.findall("Message ([0-9,-]+) ",event.get_log_string())[0]
    # print(await bot.get_msg(message_id=msg_id))
    text = str(event.get_message()).strip()
    if text:
        state["text"] = text

@say.got("text", prompt="无论说什么我都会照做的~")
async def got_name(bot: Bot,event: Event, state: T_State):
    text = state["text"]
    if text:
        await say.finish(Message(f'[CQ:tts,text="{text}"]'))
    await say.finish()