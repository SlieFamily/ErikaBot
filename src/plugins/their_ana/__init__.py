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

global rule_str

rule_str = model.GetReRule()

# 默认配置
global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

# 响应命令
theirAna = on_regex("([\u4E00-\u9FA5A-Za-z0-9_]+)语录", priority=3)
AddAna = on_regex("add ([\u4E00-\u9FA5A-Za-z0-9_]+)语录 '([\s\S]+)'", priority=2)
Addabuse = on_regex("add Erika嘴臭 '([\s\S]+)'", priority=2)
AddReRule = on_regex("update rule ([\s\S]+)", priority=1,permission=SUPERUSER)
DelAna = on_regex("del ([\u4E00-\u9FA5A-Za-z0-9_]+)语录 '([\s\S]+)'",priority=2)
Delabuse = on_regex("del Erika嘴臭 '([\s\S]+)'", priority=2)
MergeAna = on_regex("merge ([\u4E00-\u9FA5A-Za-z0-9_]+)语录 ([\u4E00-\u9FA5A-Za-z0-9_]+)语录",priority=1,permission=SUPERUSER)
LockAna = on_command("lock",priority=1,permission=SUPERUSER)
UnlockAna = on_command("unlock",priority=1,permission=SUPERUSER)
FindAna = on_regex("find '([\s\S]+)'",priority=1,permission=SUPERUSER|GROUP_ADMIN|GROUP_OWNER,)


AnaList = on_command("语录清单",priority=3)
abuse = on_regex("[\s\S]*",rule=to_me(),priority=5)
abuse2 = on_regex(rule_str,priority=5)

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
    name = state["_matched_groups"][0]
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    if name == "Erika":
        await theirAna.finish()
    my_ana = model.GetAna(name,group) #获取随机语录
    state["auto_name"] = name
    AutoAna = Matcher.new(temp=True,priority=4,default_state=state)
    @AutoAna.handle()
    async def handle(bot: Bot, event: Event, state: T_State):
        ana = event.get_message()
        if event.get_user_id() == "2450509502":
            if model.IsAdded(state["auto_name"],ana,"Auto"):
                await AutoAna.finish(Message(random.choice(rsp)))
    if my_ana:
        await theirAna.finish(Message(my_ana))
    await theirAna.finish() 

@AddAna.handle()
async def handle(bot: Bot,event: Event, state: T_State):
    name = state["_matched_groups"][0]
    ana = state["_matched_groups"][1]
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
        await DelAna.finish(Message("[CQ:image,file=78b486ef9731fb9897d1c0dc1f45eb23.image,url=https://c2cpicdw.qpic.cn/offpic_new/1364374624//1364374624-2662510851-78B486EF9731FB9897D1C0DC1F45EB23/0?term=3]\n这种垃圾语录没有存在的必要！"))
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
    name1 = state["_matched_groups"][0]
    name2 = state["_matched_groups"][1]
    flag = model.Merge(name1,name2)
    if flag:
        await MergeAna.finish(Message("[CQ:image,file=78b486ef9731fb9897d1c0dc1f45eb23.image,url=https://c2cpicdw.qpic.cn/offpic_new/1364374624//1364374624-2662510851-78B486EF9731FB9897D1C0DC1F45EB23/0?term=3]\n语录合并成功，多余的棋子就应该抛弃，是吧嘉音！"))
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
    name = re.findall("to ([\u4E00-\u9FA5A-Za-z0-9_]+)语录",state["name"])[0]
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
    name = re.findall("to ([\u4E00-\u9FA5A-Za-z0-9_]+)语录",state["name"])[0]
    print(name)
    flag = model.SetUnlock(name,state["group"])
    if flag:
        await UnlockAna.finish(Message(f"本群访问{name}语录限制解除~"))
    await UnlockAna.finish(Message("解除访问失败~"))

@FindAna.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    ana = state["_matched_groups"][0]
    infs = model.Inf(ana)
    if infs:
        await FindAna.send(Message("[CQ:image,file=91356418a33db6e251c28fae1911a1e9.image,url=https://c2cpicdw.qpic.cn/offpic_new/1364374624//1364374624-735706666-91356418A33DB6E251C28FAE1911A1E9/0?term=3]"))
        msg = f"发现{len(infs)}条同内容语录\n"
        for i in range(len(infs)):
            msg += f"第{i+1}条：\n"
            msg += f'---From: {infs[i][0]}语录\n'
            msg += '---By: '
            if infs[i][1] == "Auto":
                msg += 'Auto'
            else:
                msg += f'[CQ:at,qq={infs[i][1]}]'
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

@abuse2.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    name = state["_matched"]+"迫害"
    group = event.get_session_id()
    if not group.isdigit():
        group = group.split('_')[1]
    ana = model.GetAna(name,group)
    if ana:
        await abuse2.finish(Message(ana))
    await abuse2.finish()

@AddReRule.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    name = state["_matched_groups"][0]
    if model.UpdateReRule(name):
        await AddReRule.finish(Message("迫害库更新成功，将在下次重启后生效"))
    await AddReRule.finish(Message("胶布不想迫害大家~"))