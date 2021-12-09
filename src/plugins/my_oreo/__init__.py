import nonebot
import re
import os
from nonebot import on_command
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.adapters.cqhttp import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.permission import SUPERUSER
from .oreo import CreateImg


Oreo = on_command("order",aliases=set(['来一份', '点一个', '来点']),priority=3)

@Oreo.handle()
async def handle(bot: Bot, event: Event, state: T_State):
	msg = str(event.get_message()).strip()
	if msg:
		state["msg"] = msg

@Oreo.got("msg", prompt="？")
async def got_msg(bot: Bot,event: Event, state: T_State):
	msg = re.findall("[奥,利]+",str(state["msg"]))[0]
	if msg:
		path = CreateImg(msg)
		if path:
			path = 'file:///home/erikabot/'+path
			await Oreo.send(MessageSegment.image(file=path))
		# os.remove(path) 
		else:
			await Oreo.finish(" 吃这么多？吃奥利给吧你，老娘不干了 ")

	await Oreo.finish()