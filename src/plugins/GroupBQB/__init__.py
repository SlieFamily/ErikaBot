import nonebot
import re
from .config import Config
from nonebot import on_command,on_regex
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.adapters.cqhttp import Message,MessageSegment

from .data_source import get_image,update_img

# 默认配置
global_config = nonebot.get_driver().config
plugin_config = Config(**global_config.dict())

# 响应命令
group_bqb = on_regex("([\S]+).jpg")
add_img = on_regex("\+ img ([\S]+):%\[[\S]+url=([\S]+)\]%")

@group_bqb.handle()
async def handle_first_receive(bot: Bot, event: Event, state: T_State):
    key = re.findall("([\S]+).jpg",str(event.get_message()))[0]
    print(key)
    key_image_url = await get_image(key)
    if key_image_url:
        await group_bqb.finish(MessageSegment.image(key_image_url))

@add_img.handle()
async def handle_first_receive(bot: Bot, event: Event, state: T_State):
    dats = re.findall("\+ img ([\S]+):%\[[\S]+url=([\S]+)\]%",str(event.get_message()))[0]
    key = dats[0]
    url = dats[1]
    if update_img(key,url):
        await add_img.finish(Message(f"图片添加成功，可通过命令：{key}.jpg触发"))
    else:
        await add_img.finish(Message("添加失败，请联系工作人员"))
