import nonebot
from .config import Config
import httpx
from nonebot import on_command
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.adapters.cqhttp import Message,MessageSegment
from nonebot.log import logger


global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

setu = on_command("setu", aliases=set(['涩图', '色图', '来点色图', '来点涩图']), priority=1)

@setu.handle()
async def handle(bot: Bot, event: Event, state: T_State):
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://api.mtyqx.cn/api/random.php?return=json')
        logger.debug(resp.json())
        imgurl = resp.json()['imgurl']
        await setu.send(MessageSegment.image(imgurl))
@setu.got("str")
async def got(bot: Bot, event: Event, state: T_State):
	if state['str'] == "不够色":
		await setu.send(Message("[CQ:image,file=b874ece851685136d7b1405853f51d91.image,url=https://gchat.qpic.cn/gchatpic_new/470211570/3808573830-3003945318-B874ECE851685136D7B1405853F51D91/0?term=3,subType=0]"))
		await setu.finish(Message("要不你来发？贱坯"))
	await setu.finish()





