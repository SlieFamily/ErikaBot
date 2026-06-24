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
    获取最新动态（已适配新版 API）
    '''
    # 替换为新版 API 接口
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}&features=itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,forwardListHidden,decorationCard,commentsNewVersion,onlyfansAssetsV2,ugcDelete,onlyfansQaCard"
    
    current_cookies = load_cookies()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "Referer": f"https://space.bilibili.com/{uid}/dynamic",
        "Origin": "https://space.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Microsoft Edge";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
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

            items = res_data.get("data", {}).get("items", [])
            if not items:
                logger.warning(f"[!] UID {uid} 返回动态为空")
                return '', {}

            # --- 过滤逻辑 ---
            target_card = items[0]
            
            # 1. 过滤置顶 (检查 module_tag 是否包含“置顶”)
            if len(items) > 1:
                module_tag = target_card.get("modules", {}).get("module_tag", {})
                if module_tag and module_tag.get("text") == "置顶":
                    target_card = items[1]

            # 2. 过滤直播推送 (新版类型 DYNAMIC_TYPE_LIVE_RCMD)
            if target_card.get("type") == "DYNAMIC_TYPE_LIVE_RCMD":
                if len(items) > 1 and target_card == items[0]:
                    target_card = items[1]
                else:
                    return '', {}

            dynamic_id_str = target_card.get("id_str", "")
            return dynamic_id_str, target_card

    except Exception as e:
        logger.error(f'[!] 获取动态列表异常: {type(e).__name__}: {e}')
        return '', {}


def parse_rich_text(nodes: list) -> str:
    """
    全新解析引擎：直接解析新版 API 的 rich_text_nodes。
    无需再用容易出错的字符串 replace，原生支持文字、表情和@颜色高亮。
    """
    if not nodes:
        return ""
    
    html = ""
    for node in nodes:
        t = node.get("type")
        text = node.get("text", "")
        
        if t == "RICH_TEXT_NODE_TYPE_TEXT":
            html += text.replace("\n", "<br>")
        elif t == "RICH_TEXT_NODE_TYPE_EMOJI":
            icon_url = node.get("emoji", {}).get("icon_url", "")
            if icon_url:
                safe_alt = text.strip("[]")
                html += f'<img class="bili-emoji" src="{icon_url}" alt="{safe_alt}">'
            else:
                html += text
        elif t == "RICH_TEXT_NODE_TYPE_AT":
            html += f'<span style="color: #0284C7;">{text}</span>'
        else:
            html += text.replace("\n", "<br>")
            
    return html


def extract_dynamic_info(item: dict) -> dict:
    """
    通用数据提取器：把新版杂乱的 JSON 归一化为标准的字典，方便后续 QQ 文本和 HTML 模板共用。
    """
    info = {
        "dtype": 0,
        "type_msg": "发布了新动态",
        "content": "",
        "parsed_content": "",
        "pics": [],
        "title": "",
        "cover": "",
        "summary": "", 
        "pendant": "", 
        "decorate_card": "", 
        "reserve": None, 
        "dynamic_id": item.get("id_str", ""),
        "author_name": item.get("modules", {}).get("module_author", {}).get("name", "未知用户"),
        "avatar": item.get("modules", {}).get("module_author", {}).get("avatar", {}).get("fallback_layers", {}).get("layers", [{}])[0].get("resource", {}).get("res_image", {}).get("image_src", {}).get("remote", {}).get("url", ""),
        "timestamp": item.get("modules", {}).get("module_author", {}).get("pub_ts", time.time()),
    }

    # 如果通过上面复杂的路径没取到头像，尝试备用路径
    if not info["avatar"]:
        info["avatar"] = item.get("modules", {}).get("module_author", {}).get("face", "")

    # 1. 获取头像框 (Pendant)
    info["pendant"] = item.get("modules", {}).get("module_author", {}).get("pendant", {}).get("image", "")

    # 2. 获取右上角装扮卡片 (Decorate Card)
    info["decorate_card"] = item.get("modules", {}).get("module_author", {}).get("decorate_card", {}).get("image_enhance", "")

    # 3. 检查是否有直播预约 (Reserve)
    additional = item.get("modules", {}).get("module_dynamic", {}).get("additional", {})
    if additional and additional.get("type") == "ADDITIONAL_TYPE_RESERVE":
        res_data = additional.get("reserve", {})
        info["reserve"] = {
            "title": res_data.get("title", ""),
            "time": res_data.get("desc1", {}).get("text", ""),
            "count": res_data.get("desc2", {}).get("text", "")
        }
    
    bili_type = item.get("type", "")
    dynamic = item.get("modules", {}).get("module_dynamic", {})
    major = dynamic.get("major", {})

    # 1. 转发动态
    if bili_type == "DYNAMIC_TYPE_FORWARD":
        info["dtype"] = 1
        info["type_msg"] = "转发了一条动态"
        desc = dynamic.get("desc", {})
        nodes = desc.get("rich_text_nodes", [])
        if not nodes and desc.get("text"):
            nodes = [{"type": "RICH_TEXT_NODE_TYPE_TEXT", "text": desc.get("text")}]
            
        info["parsed_content"] = parse_rich_text(nodes)
        info["content"] = desc.get("text", "")
        
        # 递归提取原动态
        orig_item = item.get("orig", {})
        if orig_item:
            info["orig"] = extract_dynamic_info(orig_item)

    # 2. 视频投稿
    elif bili_type == "DYNAMIC_TYPE_AV":
        info["dtype"] = 8
        info["type_msg"] = "投稿了新视频"
        archive = major.get("archive", {})
        info["title"] = archive.get("title", "")
        info["cover"] = archive.get("cover", "")
        info["summary"] = archive.get("desc", "") # 这里把长介绍丢给 summary
        
        # 对于投稿，正文 parsed_content 我们放空或者用简介，因为大图视频卡片里已经有了
        info["parsed_content"] = "" 

    # 3. 图文/纯文本动态
    elif bili_type in ("DYNAMIC_TYPE_DRAW", "DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_ARTICLE"):
        info["dtype"] = 2
        info["type_msg"] = "发布了图文动态"
        opus = major.get("opus", {})
        summary = opus.get("summary", {})
        
        nodes = summary.get("rich_text_nodes", [])
        if not nodes and summary.get("text"):
            nodes = [{"type": "RICH_TEXT_NODE_TYPE_TEXT", "text": summary.get("text")}]
            
        info["parsed_content"] = parse_rich_text(nodes)
        info["content"] = summary.get("text", "")
        info["title"] = opus.get("title", "")
        
        pics = opus.get("pics", [])
        info["pics"] = [p.get("url") for p in pics]

    return info


async def get_Qmsg(name: str, datas: Dict, msg_id: str) -> Tuple[str, List[str], str]:
    '''
    将新版 API 数据转换为 QQ 可接收的纯文本信息
    '''
    info = extract_dynamic_info(datas)
    dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(info["timestamp"])))
    dynamic_url = f"https://t.bilibili.com/{info['dynamic_id']}"

    content = info["content"]
    img_list = info["pics"].copy()

    if info["dtype"] == 8:
        content = f"{info['title']}"
        if info["cover"]: img_list = [info["cover"]]

    elif info["dtype"] == 1:
        orig = info.get("orig", {})
        if orig:
            orig_name = orig.get("author_name", "未知用户")
            orig_text = orig.get("content", "")
            if orig["dtype"] == 8:
                orig_text = f"【视频】 {orig.get('title', '')}"
            content += f"\n\n转发自@{orig_name}:\n{orig_text}"
        else:
            content += "\n\n[原动态失效或被隐藏]"

    msg_text = f"你关注的 {name} {info['type_msg']}！\n\n{content}\n传送门：{dynamic_url}"
    return msg_text, img_list, dynamic_time


async def get_Htmlmsg(name: str, user_id: str, datas: Dict, msg_id: str) -> Tuple[str, str]:
    '''
    提取数据，交给 Jinja2 模板渲染，最后返回文本和本地图片路径
    '''
    info = extract_dynamic_info(datas)
    dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(info["timestamp"])))
    dynamic_url = f"https://t.bilibili.com/{info['dynamic_id']}"

    # 组装渲染数据
    template_data = {
        "avatar": info["avatar"],
        "name": name,
        "time": dynamic_time,
        "dtype": info["dtype"],
        "parsed_content": info["parsed_content"],
        "pics": info["pics"],
        "title": info["title"],
        "cover": info["cover"],
        "summary": info["summary"], 
        "pendant": info["pendant"], 
        "decorate_card": info["decorate_card"],
        "reserve": info["reserve"],  
        "orig_name": "",
        "orig_parsed_content": "",
        "orig_pics": []
    }

    # 处理转发内容的嵌套渲染
    if info["dtype"] == 1:
        orig = info.get("orig", {})
        if orig:
            template_data["orig_name"] = orig.get("author_name", "未知用户")
            if orig["dtype"] == 8:
                template_data["orig_parsed_content"] = f"投稿了视频<br><b>{orig.get('title', '')}</b>"
                template_data["orig_pics"] = [orig.get("cover")] if orig.get("cover") else []
            else:
                template_data["orig_parsed_content"] = orig.get("parsed_content", "")
                template_data["orig_pics"] = orig.get("pics", [])
        else:
            template_data["orig_parsed_content"] = "[原动态失效或被隐藏]"

    # 执行 Playwright 渲染
    output_img_name = f"dynamic_{user_id}.png"
    img_path = await biliRender.render_to_image(template_data, output_img_name)

    msg_text = f"你关注的 {name} {info['type_msg']}！"
    img_list = [img_path]
    
    return msg_text, img_list, dynamic_url