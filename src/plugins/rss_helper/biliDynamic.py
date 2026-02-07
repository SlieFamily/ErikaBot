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
        return info['anchor_info']['base_info']['name']
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
        return str_hash(time),datas
    except:
        logger.error('[!]RSS访问失败，请检查订阅url或代理/网络设置！')
        logger.error('[!]获取订阅消息失败！')
        return '',[]
    


async def get_Qmsg(name:str, datas:list, msg_id:str)->list:
    '''
    将获得的信息转换为QQ可接收的信息(含翻译选项)
    返回 文本信息、媒体信息(图片)、时间戳
    '''
    trans_msg = ''
    msgs = []
    if msg_id == '': #第一次关注则只刷新最新一条
        datas = [datas[0]]
    for data in datas[:10]:
        if str_hash(data['published']) == msg_id: #从最新动态往下更新，直到与上次记录重合
            break
        else:
            html = Pq(data['summary'])
            msg = handle_html_tag(html)
            imgs= [item.attr('src') for item in html('img').items()]

            # 将 GMT 时间转换为 北京时间
            publish_time = data['published_parsed']
            publish_time = time.mktime(publish_time)+28800
            publish_time = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(publish_time))
            msgs.insert(0,(msg,imgs,publish_time))

    return msgs
    
# 百度翻译
async def baidu_translate(msg):
    pass
