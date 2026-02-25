import httpx
import random
import hashlib
import os
import time
from nonebot.log import logger
from typing import Any, Dict, List
import feedparser
from pyquery import PyQuery as Pq
from utils.HtmlTag import handle_html_tag


# 对字符串计算哈希值，供后续比较
def str_hash(string: str) -> str:
    res = hashlib.md5(string.encode())
    return res.hexdigest()


    
async def get_user_info(url:str)->str:
    '''
    根据订阅信息的url获取作者昵称
    '''
    try:
        rss = feedparser.parse(url)
        try:
            msg = rss.entries[0]['author']
        except:
            msg = rss.feed.title.split(" ")[0] #解决B站动态没有作者信息问题
        logger.success('[√]订阅消息获取成功！')  #存在因订阅源失效导致xml内容无用的情况，待修复
        return msg

    except:
        logger.error('[!]RSS访问失败，请检查订阅url或代理/网络设置！')
        logger.error('[!]获取订阅消息失败！')
        return ''


async def get_latest_datas(url:str)->(str,list):
    '''
    根据订阅信息的url检查更新
    返回信息唯一标识和最新数据
    '''
    try:
        rss = feedparser.parse(url)
        datas = rss.entries
        time = datas[0]['published']
        logger.success('[√]订阅消息刷新成功！')  #存在因订阅源失效导致xml内容无用的情况，待修复
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
    msg = f'你关注的 {name} 发布新微博啦！\n\n'
    data = datas[0]
    if str_hash(data['published']) == msg_id: #从最新动态往下更新，直到与上次记录重合
        return ()
    else:
        html = Pq(data['summary'])
        msg += handle_html_tag(html)
        imgs= [item.attr('src') for item in html('img').items()]
        # 将 GMT 时间转换为 北京时间
        publish_time = data['published_parsed']
        publish_time = time.mktime(publish_time)+28800
        publish_time = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(publish_time))

    return msg, imgs, publish_time