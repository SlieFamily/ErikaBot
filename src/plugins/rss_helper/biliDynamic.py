import httpx
import json
import time
import os
import asyncio
from typing import Any, Dict, List, Tuple
from nonebot.log import logger
from bilibili_api import user
from . import biliRender  # 导入渲染工具

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
    获取最新动态（旧版API更稳定）
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
    # if len(content) > 200:
    #     content = content[:200] + "..."

    dynamic_url = f"https://t.bilibili.com/{desc.get('dynamic_id_str')}"
    msg_text = (
        f'你关注的 {name} {type_msg}！\n\n'
        f'{content}\n'
        f'传送门：{dynamic_url}'
    )

    return msg_text, img_list, dynamic_time


def parse_text_and_emojis(text: str, display_info: dict) -> str:
    """
    核心：将文本中的 [doge] 替换为 HTML <img> 标签
    """
    if not text:
        return ""
    
    parsed_text = text.replace('\n', '<br>')
    
    emoji_info = display_info.get("emoji_info") or {}
    emoji_details = emoji_info.get("emoji_details") or []
    
    # 1. 提取有效表情并【去重】（利用字典的键唯一性过滤重复表情）
    unique_emojis = {
        e.get("emoji_name"): e.get("url") 
        for e in emoji_details 
        if e.get("emoji_name") and e.get("url")
    }
    
    # 2. 按表情名字长度【降序排序】
    # 防止 [doge] 错误地把 [doge_大笑] 的前半部分给替换了
    sorted_emojis = sorted(unique_emojis.items(), key=lambda x: len(x[0]), reverse=True)
    
    for name, url in sorted_emojis:
        # 3. 【关键修复】去掉 alt 中的中括号
        # 如果 name 是 "[doge]"，safe_alt 就是 "doge"
        # 这样即使逻辑出错，也永远不会匹配到 alt="doge" 上去
        safe_alt = name.strip("[]")
        
        img_tag = f'<img class="bili-emoji" src="{url}" alt="{safe_alt}">'
        parsed_text = parsed_text.replace(name, img_tag)
            
    return parsed_text

async def get_Htmlmsg(name: str, user_id: str, datas: Dict, msg_id: str) -> Tuple[str, str]:
    '''
    提取 JSON 数据，交给模板渲染，最后返回 QQ 文本和【生成的本地图片路径】
    '''
    desc = datas.get('desc', {})
    display = datas.get('display', {})
    
    try:
        card = json.loads(datas.get('card', '{}'))
    except:
        card = {}

    timestamp = desc.get('timestamp', time.time())
    dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(timestamp)))
    dtype = desc.get('type')
    dynamic_url = f"https://t.bilibili.com/{desc.get('dynamic_id_str')}"

    # 初始化准备传给 Jinja2 的数据包
    template_data = {
        "avatar": desc.get('user_profile', {}).get('info', {}).get('face', ''),
        "name": name,
        "time": dynamic_time,
        "dtype": dtype,
        "parsed_content": "",
        "pics": [],
        "title": "",
        "cover": "",
        "orig_name": "",
        "orig_parsed_content": "",
        "orig_pics": []
    }
    if dtype == 2: # 图文
        type_msg = "发布了新动态"
        item = card.get('item', {})
        raw_text = item.get('description', '')
        template_data["parsed_content"] = parse_text_and_emojis(raw_text, display)
        if 'pictures' in item and item['pictures_count']  > 0: 
            template_data["pics"] = [p.get('img_src') for p in item['pictures']]

    elif dtype == 8: # 视频
        type_msg = "投稿了新视频"
        template_data["parsed_content"] = parse_text_and_emojis(card.get('dynamic', ''), display)
        template_data["title"] = card.get('title', '')
        template_data["cover"] = card.get('pic', '')

    elif dtype == 1: # 转发
        type_msg = "转发了一条动态"
        raw_text = card.get('item', {}).get('content', '')
        template_data["parsed_content"] = parse_text_and_emojis(raw_text, display)
        
        # 解析原动态
        if 'origin' in card:
            origin = json.loads(card['origin'])
            orig_type = desc.get('orig_type')
            template_data["orig_name"] = origin.get('user', {}).get('name') or origin.get('owner', {}).get('name', '未知用户')
            
            orig_text = ""
            if orig_type == 8: 
                orig_text = f"投稿了视频\n{origin.get('title', '')}"
                template_data["orig_pics"] = [origin.get('pic', '')]
            elif orig_type == 2:
                orig_text = origin.get('item', {}).get('description', '')
                if 'pictures' in origin.get('item', {}):
                    template_data["orig_pics"] = [p.get('img_src') for p in origin.get('item')['pictures']]
            else:
                orig_text = origin.get('item', {}).get('content', '查看详情')
            
            # 提取原动态表情 (如果有)
            orig_display = display.get('origin', {})
            template_data["orig_parsed_content"] = parse_text_and_emojis(orig_text, orig_display)

    # except Exception as e:
    #     logger.error(f"构建模板数据失败: {e}")
    #     template_data["parsed_content"] = "内容解析失败，请点击链接查看。"

    # 执行渲染
    output_img_name = f"dynamic_{user_id}.png"
    img_path = await biliRender.render_to_image(template_data, output_img_name)

    # 返回极简的提示文本 + 渲染好的图片路径
    msg_text = f"你关注的 {name} {type_msg}！"
    img_list = [img_path]
    return msg_text, img_list, dynamic_url