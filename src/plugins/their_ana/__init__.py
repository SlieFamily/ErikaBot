import nonebot
import re
import math
from .config import Config
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot,Event
from nonebot.params import State, ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER, PRIVATE_FRIEND
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
DelAna = on_regex("del ("+anas_rule+")：([\s\S]+)",priority=2)
MergeAna = on_regex("merge ("+anas_rule+")，("+anas_rule+")",priority=1,permission=SUPERUSER)
LockAna = on_command("lock",priority=1,permission=SUPERUSER)
UnlockAna = on_command("unlock",priority=1,permission=SUPERUSER)
DelAllAna = on_command("drop",priority=1,permission=SUPERUSER)
Rename = on_regex("rename ("+anas_rule+") to ("+anas_rule+")",priority=1,permission=SUPERUSER)
FindAna = on_regex("find：([\s\S]+)",priority=1)
SuperAna = on_regex("[\w\W]+",priority=5)
AnaList = on_command("语录清单",priority=3)
abuse = on_regex("[\s\S]*",rule=to_me(),priority=5)
abuse_chg = on_regex("([\w\W]+)嘲讽状态",priority=1,permission=SUPERUSER)


@AnaList.handle()
async def handle(bot: Bot, event: Event, state: T_State = State(), page: Message = CommandArg()):
    names1,cnts1 = model.GetList()
    names2,cnts2 = model.GetSuperList()
    names = names1+names2; cnts = cnts1+cnts2
    msg = '\n'
    if len(names) <= 20:
        for i in range(len(cnts)):
            msg += names[i]+'语录 \t('+ str(cnts[i]) +'条)\n'
        if msg:
            await AnaList.finish(Message(msg))
        else:
            await AnaList.finish()
    else:
        page = str(page)
        res = re.findall("-(\d+)",page)
        if res:
            state['page'] = int(res[0])-1
        else:
            await AnaList.send(Message(f"由于当前语录清单内容过长，胶布已将其分为{math.ceil(len(names)/20)}页。\n\n请发送：语录清单-x 来查看。\n[x为页码]"))

@AnaList.got("page")
async def got_page(bot: Bot,event: Event, state: T_State = State(), page: int = Arg("page")):
    names1,cnts1 = model.GetList()
    names2,cnts2 = model.GetSuperList()
    names = names1+names2; cnts = cnts1+cnts2
    gp_names = []; gp_cnts = []; msg = '\n';page = state['page']

    for i in range(0,len(names),20):
        gp_names.append(names[i:i+20])
        gp_cnts.append(cnts[i:i+20])

    if page > math.ceil(len(names)/20):
        await AnaList.finish(Message("告诉你有这么多页了？"))
    for i in range(len(gp_names[page])):
        msg += gp_names[page][i]+'语录 \t('+ str(gp_cnts[page][i]) +'条)\n'
    if msg:
        await AnaList.finish(Message(msg))
    await AnaList.finish()

@theirAna.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
    name = state["_matched_groups"]
    name = name[1] if name[1] else name[2]
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    my_ana = model.GetAna(name,group) #获取随机语录
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
    #     except:
    #         pass
    if my_ana:
        await theirAna.finish(Message(my_ana))
    await theirAna.finish() 

@AddAna.handle()
async def handle(bot: Bot,event: Event, state: T_State = State()):
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

@DelAna.handle()
async def handle(bot: Bot,event: Event, state: T_State = State()):
    name = state["_matched_groups"]
    name = name[1] if name[1] else name[2]
    ana = state["_matched_groups"][3]
    del_msg = model.IsDel(name,ana)
    if del_msg:
        await DelAna.finish(Message("这种垃圾语录没有存在的必要！"))
    await DelAna.finish(Message("失败了失败了失败了……"))

@MergeAna.handle()
async def handle(bot: Bot,event: Event, state: T_State = State()):
    name1 = state["_matched_groups"]
    name1 = name1[1] if name1[1] else name1[2]
    name2 = state["_matched_groups"]
    name2 = name2[4] if name2[4] else name2[5]
    flag = model.Merge(name1,name2)
    if flag:
        await MergeAna.finish(Message("语录合并成功，多余的棋子就应该抛弃，是吧嘉音！"))
    await MergeAna.finish(Message("家具就是家具，无法成为人！"))

@LockAna.handle()
async def handle(bot: Bot,event: Event, state: T_State = State(), name: Message = CommandArg()):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    state["group"] = group
    if name:
        state["name"] = name

@LockAna.got("name", prompt="该限制什么语录呢？")
async def got_name(bot: Bot,event: Event, state: T_State = State(), name: Message = Arg("name"), group: str = Arg("group")):
    print("---",name,group)
    name = re.findall("to ([\w\W]+)语录",str(name))[0]
    flag = model.SetLock(name,group)
    if flag:
        await LockAna.finish(Message(f"本群已限制访问{name}语录~"))
    await LockAna.finish(Message("禁止访问失败~"))

@UnlockAna.handle()
async def handle(bot: Bot,event: Event, state: T_State = State() ,name: Message = CommandArg()):
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    state["group"] = group
    if name:
        state["name"] = name

@UnlockAna.got("name", prompt="该解除什么语录呢？")
async def got_name(bot: Bot,event: Event, state: T_State = State(), name: Message = Arg("name"), group: str = Arg("group")):
    print("---",name,group)
    name = re.findall("to ([\w\W]+)语录",str(name))[0]
    flag = model.SetUnlock(name,group)
    if flag:
        await UnlockAna.finish(Message(f"本群访问{name}语录限制解除~"))
    await UnlockAna.finish(Message("解除访问失败~"))

@DelAllAna.handle()
async def handle(bot: Bot,event: Event, state: T_State = State(), name: Message = CommandArg()):
    if name:
        state["name"] = name

@DelAllAna.got("name", prompt="啊~全都要摧毁！全都要！")
async def got_name(bot: Bot,event: Event, state: T_State = State(), name: Message = Arg("name")):
    print(name)
    name = re.findall("([\w\W]+)语录",str(name))[0]
    flag = model.DropAna(name)
    if flag:
        await DelAllAna.finish(Message(f"果然{name}语录，就是应该狼狈退场呢~"))
    await DelAllAna.finish(Message("嘁，让他侥幸存活了"))

@FindAna.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
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
async def handle(bot: Bot, event: GroupMessageEvent, state: T_State = State()):
    name = "Erika"
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    my_ana = model.GetAna(name,group)
    if my_ana:
        await abuse.finish(Message(my_ana))
    await abuse.finish()

@abuse_chg.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
    status = state["_matched_groups"][0]
    group = event.get_session_id()
    name = "Erika"
    # print(status)
    if status == '关闭':
        flag = model.SetLock(name,group)
        if flag:
            await abuse_chg.finish(Message(f'嘲讽状态[{status}]，试试@我一下吧~'))
    elif status == '开启':
        flag = model.SetUnlock(name,group)
        if flag:
            await abuse_chg.finish(Message(f'嘲讽状态[{status}]，试试@我一下吧~'))

@SuperAna.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
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
async def handle(bot: Bot, event: Event, state: T_State = State()):
    name1 = state["_matched_groups"]
    name1 = name1[1] if name1[1] else name1[2]
    name2 = state["_matched_groups"]
    name2 = name2[4] if name2[4] else name2[5]
    if model.RenameAna(name1,name2):
        await Rename.finish(Message("*进行Psync成功*"))
    await Rename.finish(Message("还是好好呆着吧~"))
