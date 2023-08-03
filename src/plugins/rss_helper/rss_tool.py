import httpx
import random
import hashlib
import os
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
            msg = rss.feed.title.split(" ")[0] #解决B站动态没有作者信息
        logger.success('[√]订阅消息获取成功！')  #存在因订阅源失效导致xml内容无用的情况，待修复
        return msg

    except:
        logger.error('[!]RSS访问失败，请检查订阅url或代理/网络设置！')
        logger.error('[!]获取订阅消息失败！')
        return ''


async def get_latest_msg(url:str)->(str,str):
    '''
    根据订阅信息的url检查更新
    返回信息唯一标识 msg_id 和 更新内容 msg
    '''
    try:
        rss = feedparser.parse(url)
        msg = rss.entries[0]['summary']
        logger.success('[√]订阅消息刷新成功！')  #存在因订阅源失效导致xml内容无用的情况，待修复
        return str_hash(msg),msg

    except:
        logger.error('[!]RSS访问失败，请检查订阅url或代理/网络设置！')
        logger.error('[!]获取订阅消息失败！')
        return '',''
    


async def get_Qmsg(name:str, data:str):
    '''
    将获得的信息转换为QQ可接收的信息(含翻译选项)
    返回 文本信息、媒体信息(图片)
    '''
    text = f'您关注的 【{name}】 更新了：\n\n'
    trans_msg = ''
    html = Pq(data)
    msg = handle_html_tag(html)
    imgs= [item.attr('src') for item in html('img').items()]

    return text+msg,imgs
    
# 百度翻译
async def baidu_translate(msg):
    pass
