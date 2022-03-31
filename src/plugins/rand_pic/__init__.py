import nonebot
from .config import Config
import httpx
import random
from nonebot import on_command
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.params import State, ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.log import logger


global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

imgs = [
	"[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/bugouse.png]",

	]

setu = on_command("setu", aliases=set(['涩图', '色图', '来点色图', '来点涩图']), priority=1)

@setu.handle()
async def handle(bot: Bot, event: Event, state: T_State = State()):
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://api.mtyqx.cn/api/random.php?return=json')
        logger.debug(resp.json())
        imgurl = resp.json()['imgurl']
        await setu.send(MessageSegment.image(imgurl))

@setu.got("str")
async def got(bot: Bot, event: Event, state: T_State= State(), msg: str = ArgPlainText("str")):
	if msg == "不够色":
		await setu.finish(Message("要不你来发？贱坯\n"+random.choice(imgs)))
	await setu.finish()





