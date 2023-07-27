import nonebot
from .config import Config
import httpx
import random
from nonebot import on_command
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.params import ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.log import logger


global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

imgs = [
    "[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/bugouse.png]",

    ]

setu = on_command("setu", aliases=set(['涩图', '色图', '来点色图', '来点涩图']), priority=1)

@setu.handle()
async def handle(bot: Bot, event: Event ):
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://api.lolicon.app/setu/v2?r18=0&size=regular')
        logger.debug(resp.json())
        print(resp.json())
        imgurl = resp.json()['data'][0]['urls']['regular']
        pid = resp.json()['data'][0]['pid']
        title = resp.json()['data'][0]['title']
        await setu.send(MessageSegment.image(imgurl))

@setu.got("str")
async def got(bot: Bot, event: Event, msg: str = ArgPlainText("str")):
    if msg == "加大剂量":
        async with httpx.AsyncClient() as client:
            resp = await client.get('https://api.lolicon.app/setu/v2?r18=1&size=thumb')
            logger.debug(resp.json())
            print(resp.json())
            imgurl = resp.json()['data'][0]['urls']['thumb']
            await setu.send(MessageSegment.image(imgurl))
    if msg == "不够色" or msg == "不够涩":
        await setu.finish(Message("要不你来发？贱坯\n"+random.choice(imgs)))
    await setu.finish()




