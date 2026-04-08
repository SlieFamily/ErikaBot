import httpx
import random
import hashlib
import os
import time
from nonebot.log import logger
from bilibili_api import live, sync
from typing import Any, Dict, List
from . import biliRender  # 导入渲染工具


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
    except Exception as e:
        logger.error(f'[!]获取直播间信息失败！Room ID: {room_id}, 错误: {e}')
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
        logger.success(f'[√]订阅消息刷新成功。Live Status: {live_status}')
        return str(live_status), datas
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

async def get_Htmlmsg(name: str, user_id:str, datas: dict, msg_id: str) -> tuple[str, str]:
    '''
    将直播信息放入 live.html 模板渲染，返回 提示文本 和 图片本地路径
    '''
    title = datas.get('title', '无标题')
    cover = datas.get('cover', '')
    area = datas.get('area_name', '未知分区')
    
    # 转换时间
    live_start_time = datas.get('live_start_time', time.time())
    live_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(live_start_time))
    
    # 直播间链接
    room_id = datas.get('room_id', '')
    live_url = f"https://live.bilibili.com/{room_id}"


    # 组装丢给 Jinja2 模板的数据字典
    template_data = {
        "name": name,
        "cover": cover,
        "area": area,
        "title": title,
        "live_time": live_time
    }

    # 调用渲染工具，注意这里传入 template_name="live.html"
    output_img_name = f"live_{room_id}_{msg_id}.png"
    img_path = await biliRender.render_to_image(
        template_data=template_data, 
        output_filename=output_img_name, 
        template_name="live.html"
    )
    # 构造极简的 QQ 文本（图片里已经有所有详细信息了）
    msg_text = f"你关注的 {name} 开播啦！"
    
    return msg_text, [img_path], live_url
