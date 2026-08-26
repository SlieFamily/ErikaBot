import httpx
import random
import hashlib
import os
import time
import asyncio
from nonebot.log import logger
from typing import Any, Dict, List, Tuple
import feedparser
from pyquery import PyQuery as Pq
from utils.HtmlTag import handle_html_tag

# 创建全局异步HTTP客户端，配置15秒超时
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=10.0),
    follow_redirects=True
)


# 对字符串计算哈希值，供后续比较
def str_hash(string: str) -> str:
    res = hashlib.md5(string.encode())
    return res.hexdigest()


    
async def get_user_info(url:str)->str:
    '''
    根据订阅信息的url获取作者昵称
    '''
    try:
        # 异步获取RSS内容，自动应用15秒超时
        response = await _http_client.get(url)
        response.raise_for_status()

        # 在线程池中解析RSS（feedparser是同步的，避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        rss = await loop.run_in_executor(None, feedparser.parse, response.text)

        try:
            msg = rss.entries[0]['author']
        except:
            msg = rss.feed.title.split(" ")[0]
        logger.success('[√]订阅消息获取成功！')
        return msg

    except httpx.TimeoutException:
        logger.error(f'[!]RSS访问超时: {url}')
        return ''
    except Exception as e:
        logger.error(f'[!]RSS访问失败: {e}')
        return ''


async def get_latest_datas(url:str) -> Tuple[str, List]:
    '''
    根据订阅信息的url检查更新
    返回信息唯一标识和最新数据
    '''
    try:
        # 异步获取RSS内容，自动应用15秒超时
        response = await _http_client.get(url)
        response.raise_for_status()

        # 在线程池中解析RSS（feedparser是同步的，避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        rss = await loop.run_in_executor(None, feedparser.parse, response.text)

        datas = rss.entries
        if not datas:
            logger.warning('[!]RSS内容为空')
            return '', []

        time = datas[0]['published']
        logger.success('[√]订阅消息刷新成功！')
        return str_hash(time), datas

    except httpx.TimeoutException:
        logger.error(f'[!]RSS访问超时: {url}')
        return '', []
    except Exception as e:
        logger.error(f'[!]获取订阅消息失败: {e}')
        return '', []
    


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