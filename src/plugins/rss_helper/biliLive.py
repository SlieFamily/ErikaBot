import httpx
import random
import hashlib
import os
import time
from nonebot.log import logger
from bilibili_api import live, sync
from typing import Any, Dict, List
from utils.HtmlTag import handle_html_tag


# 对字符串计算哈希值，供后续比较
def str_hash(string: str) -> str:
    res = hashlib.md5(string.encode())
    return res.hexdigest()

    
async def get_user_info(room_id:str)->str:
    '''
    根据直播间号获取作者昵称
    '''
    try:
        room = live.LiveRoom(room_id)
        info = await room.get_room_info()
        return info['anchor_info']['base_info']['uname']
    except:
        logger.error('[!]RSS访问失败，请检查订阅url或代理/网络设置！')
        logger.error('[!]获取订阅消息失败！')
        return ''


async def get_latest_datas(room_id:str):
    '''
    根据直播间号检查更新
    返回信息唯一标识和最新数据
    '''
    try:
        room = live.LiveRoom(room_id)
        info = await room.get_room_info()
        datas = info['room_info']
        live_status = datas['live_status']
        logger.success('[√]订阅消息刷新成功！')
        if live_status == 1:
            return str_hash(str(datas['live_status'])), datas
        else:
            return '', []
    except:
        logger.error('[!]RSS访问失败，请检查订阅url或代理/网络设置！')
        logger.error('[!]获取订阅消息失败！')
        return '',[]
    


async def get_Qmsg(name:str, datas:list, msg_id:str)->list:
    '''
    将获得的信息转换为QQ可接收的信息(含翻译选项)
    返回 文本信息、媒体信息(图片)、时间戳
    '''
    title = datas['title']
    cover = datas['cover']
    area = datas['area_name']
    live_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(datas['live_start_time']))
    live_url = f"https://live.bilibili.com/{datas['room_id']}"
    msgs = (
        f'你关注的 {name} 开播啦！\n\n分区：{area}\n标题：{title}\n传送门：{live_url}',
        [cover],
        live_time
    )
    return msgs
