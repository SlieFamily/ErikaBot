import nonebot
from .config import Config
import httpx
import random
import os
import time
from nonebot import on_command
from nonebot.rule import to_me
from nonebot.adapters import Bot, Event
from nonebot.params import ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent,PokeNotifyEvent
from nonebot.log import logger
from utils.QImage import image_download
from typing import Any, Dict, List, Tuple, Optional, Union

global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

# 获取Bot主目录
path = os.path.abspath(os.getcwd())

imgs = [
    "[CQ:image,file=https://cdn.jsdelivr.net/gh/SlieFamily/TempImages@main//Auto/bugouse.png]",#竖中指图

    ]
msg_id = ''

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.36"
}

setu = on_command("setu", aliases=set(['涩图', '色图', '来点色图', '来点涩图']), priority=1)


async def get_msg_id(
    bot: Bot, e: Optional[Exception], api: str, data: Dict[str, Any], result: Any
):
    try: #确认api属群聊还是私聊
        if api in ["send_msg", "send_forward_msg"]:
            msg_type = data["message_type"]
            id = data["group_id"] if msg_type == "group" else data["user_id"]
        elif api in ["send_private_msg", "send_private_forward_msg"]:
            msg_type = "private"
            id = data["user_id"]
        elif api in ["send_group_msg", "send_group_forward_msg"]:
            msg_type = "group"
            id = data["group_id"]
        else:
            return
        # 获取msg_id
        global msg_id
        msg_id = str(result["message_id"])
        print('[!]消息已发出，message_id：',msg_id)

    except:
        pass

Bot.on_called_api(get_msg_id)


@setu.handle()
async def handle(bot: Bot, event: Event ):
    async with httpx.AsyncClient() as client:
        resp = await client.get('https://api.lolicon.app/setu/v2?r18=0&size=regular', headers = headers)
        print(resp.json())
        url = resp.json()['data'][0]['urls']['regular']
        imgurl = url.replace('i.pixiv.re','px3.rainchan.win')
        print(imgurl)
        # imgurl = image_download(imgurl,'setu',False)
        # imgurl = 'file://'+path+'/imgs/'+imgurl
        # print(imgurl)
    
        try:
            await setu.send(MessageSegment.image(imgurl))
        except:
            await setu.finish(Message("图片发送失败，申鹤冲晕了~"))
@setu.got("str")
async def got(bot: Bot, event: Event, msg: str = ArgPlainText("str")):
    if msg == "加大剂量":
        async with httpx.AsyncClient() as client:
            resp = await client.get('https://api.lolicon.app/setu/v2?r18=2&size=small', headers = headers)
            print(resp.json())
            url = resp.json()['data'][0]['urls']['small']
            imgurl = url.replace('i.pixiv.re','px3.rainchan.win')
            print(imgurl)
            # imgurl = image_download(imgurl,'setu',False)
            # imgurl = 'file://'+path+'/imgs/'+imgurl
            # print(imgurl)
            try:
                await setu.send(MessageSegment.image(imgurl))
            except:
                await setu.finish(Message("图片发送失败，菲泽利努冲晕了~"))
            try:
                time.sleep(5)
                await bot.delete_msg(message_id = int(msg_id))
                await setu.finish(Message("欸嘿~ 这是我和德拉的秘密"))
            except:
                await setu.finish()


    if msg == "不够色" or msg == "不够涩":
        await setu.finish(Message("要不你来发？贱坯\n"+random.choice(imgs)))
    await setu.finish()




