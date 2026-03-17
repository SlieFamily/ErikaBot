import httpx
import json
import time
import os
from typing import Any, Dict, List, Tuple
from nonebot.log import logger
from bilibili_api import user


async def get_user_info(uid: str) -> str:
    '''
    根据用户UID获取作者昵称
    '''
    try:
        u = user.User(int(uid))
        info = await u.get_user_info() # 获取基本关系信息，含昵称
        return info['name']
    except Exception as e:
        logger.error(f'[!]获取用户信息失败！UID: {uid}, 错误: {e}')
        return ''


COOKIE_PATH = os.path.join(os.path.dirname(__file__), "biliCookie.json")


def load_cookies() -> Dict[str, str]:
    '''
    从外部 JSON 文件加载 Cookie
    '''
    if not os.path.exists(COOKIE_PATH):
        logger.error(f"[!] 未找到 Cookie 文件: {COOKIE_PATH}")
        return {}
    try:
        with open(COOKIE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[!] 读取 Cookie 文件失败: {e}")
        return {}


async def get_latest_datas(uid: str) -> Tuple[str, Dict]:
    '''
    获取最新动态（旧版API）
    '''
    url = f"https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history?host_uid={uid}"
    
    current_cookies = load_cookies()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
        "Accept": "application/json, text/plain, */*"
    }

    try:
        async with httpx.AsyncClient(
            headers=headers, 
            cookies=current_cookies, 
            timeout=15.0, 
            verify=False
        ) as client:
            res = await client.get(url)
            res_data = res.json()

            if res_data.get("code") != 0:
                logger.error(f"[!] 业务错误 (UID {uid}): {res_data.get('message')}")
                return '', {}

            cards = res_data.get("data", {}).get("cards", [])
            if not cards or cards is None:
                # 如果带了 Cookie 依然返回 None，通常是节点被风控
                logger.warning(f"[!] UID {uid} 返回动态为空 (可能触发风控)")
                return '', {}

            # --- 过滤逻辑 ---
            target_card = cards[0]
            
            # 1. 过滤置顶 (ID 比较法)
            if len(cards) > 1:
                id0 = target_card['desc']['dynamic_id']
                id1 = cards[1]['desc']['dynamic_id']
                if id0 < id1:
                    target_card = cards[1]

            # 2. 过滤直播 (旧版类型 4308)
            dtype = target_card['desc'].get('type')
            if dtype == 4308:
                if len(cards) > 1 and target_card == cards[0]:
                    target_card = cards[1]
                else:
                    return '', {}

            dynamic_id_str = target_card['desc']['dynamic_id_str']
            # 返回 ID 的 hash 值和原始数据
            return dynamic_id_str, target_card

    except Exception as e:
        logger.error(f'[!] 获取动态列表异常: {type(e).__name__}: {e}')
        return '', {}



async def get_Qmsg(name: str, datas: Dict, msg_id: str) -> Tuple[str, List[str], str]:
    '''
    将旧版 API 的数据转换为 QQ 可接收的信息
    '''
    desc = datas.get('desc', {})
    # 核心：旧版 API 的内容在 card 字符串里
    try:
        card = json.loads(datas.get('card', '{}'))
    except:
        card = {}

    # 1. 获取时间
    timestamp = desc.get('timestamp', time.time())
    dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(timestamp)))

    # 2. 解析类型 (旧版是 int)
    dtype = desc.get('type')
    
    content = ""
    img_list = []
    type_msg = "发布了新动态"

    try:
        # 3.1 图文动态 (Type 2)
        if dtype == 2:
            type_msg = "发布了图文动态"
            item = card.get('item', {})
            content = item.get('description', '')
            if 'pictures' in item and item['pictures_count']  > 0: 
                img_list = [p.get('img_src') for p in item['pictures']]

        # 3.2 纯文字动态 (Type 4)
        elif dtype == 4:
            type_msg = "发布了文字动态"
            content = card.get('item', {}).get('content', '')

        # 3.3 视频投稿 (Type 8)
        elif dtype == 8:
            type_msg = "投稿了新视频"
            content = f"{card.get('title')}"
            if card.get('pic'):
                img_list = [card['pic']]

        # 3.4 专栏文章 (Type 64)
        elif dtype == 64:
            type_msg = "发布了专栏文章"
            content = f"{card.get('title')}\n{card.get('summary')}"
            if card.get('image_urls'):
                img_list = card['image_urls'][:1] # 取封面

        # 3.5 转发动态 (Type 1)
        elif dtype == 1:
            type_msg = "转发了一条动态"
            content = card.get('item', {}).get('content', '')
            # 获取原动态简述
            orig_type = desc.get('orig_type')
            if 'origin' in card:
                try:
                    origin = json.loads(card['origin'])
                    # 尝试从原动态提取一点点文本
                    orig_text = ""
                    if orig_type == 8: orig_text = f"【视频】 {origin.get('title')}"
                    elif orig_type == 64: orig_text = f"【专栏】 {origin.get('title')}"
                    else: orig_text = origin.get('item', {}).get('description', '') or origin.get('item', {}).get('content', '查看详情')
                    
                    user_name = origin.get('user', {}).get('name') or origin.get('owner', {}).get('name') or '未知用户'
                    content += f"\n\n转发自@{user_name}:\n{orig_text}"
                except:
                    content += "\n\n[原动态查看链接]"

        else:
            content = "请点击链接查看详情"

    except Exception as e:
        logger.error(f"解析旧版动态内容出错: {e}")
        content = "内容解析失败"

    # 限制长度
    if len(content) > 200:
        content = content[:200] + "..."

    dynamic_url = f"https://t.bilibili.com/{desc.get('dynamic_id_str')}"
    msg_text = (
        f'你关注的 {name} {type_msg}！\n\n'
        f'{content}\n'
        f'传送门：{dynamic_url}'
    )

    return msg_text, img_list, dynamic_time