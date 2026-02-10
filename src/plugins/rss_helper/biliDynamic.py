import hashlib
import time
from nonebot.log import logger
from bilibili_api import user, sync, Credential
from typing import Any, Dict, List, Tuple, Optional


# 对字符串计算哈希值，供后续比较
def str_hash(string: str) -> str:
    res = hashlib.md5(string.encode())
    return res.hexdigest()

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

async def get_latest_datas(uid: str) -> Tuple[str, Dict]:
    '''
    获取最新动态：跳过置顶，跳过直播相关
    '''
    try:
        u = user.User(int(uid))
        res = await u.get_dynamics_new()
        if res and 'items' in res and res['items']:
            for card in res['items']:
                # 1. 检查是否为置顶
                is_top = False
                if card.get('modules', {}).get('module_tag'):
                    if card['modules']['module_tag'].get('text') == '置顶':
                        is_top = True
                
                # 2. 检查是否为直播信息
                # DYNAMIC_TYPE_LIVE_RCMD: 直播开播推荐
                # DYNAMIC_TYPE_COMMON_BUSINESS: 包含直播预约等业务
                dtype = card.get('type')
                is_live = dtype in ['DYNAMIC_TYPE_LIVE_RCMD', 'DYNAMIC_TYPE_COMMON_BUSINESS']
                
                # 补充判断：有些直播信息在 module_dynamic 的 major 里标记为 live
                if not is_live:
                    major_type = card.get('modules', {}).get('module_dynamic', {}).get('major', {}).get('type')
                    if major_type == 'MAJOR_TYPE_LIVE':
                        is_live = True

                # 只有既不是置顶，也不是直播，才是我们要的“正经”动态
                if not is_top and not is_live:
                    dynamic_id = card['id_str']
                    return str_hash(dynamic_id), card
            
            # 如果循环结束都没找到合适动态（全是直播或置顶）
            return '', {}
            
        return '', {}
    except Exception as e:
        logger.error(f'[!]获取动态列表异常: {e}')
        return '', {}

async def get_Qmsg(name: str, datas: Dict, msg_id: str) -> Tuple[str, List[str], str]:
    '''
    将 get_dynamics_new 的数据转换为QQ可接收的信息
    返回 文本信息、媒体信息(图片列表)、时间戳
    '''
    # --- 新版 API 数据结构解析 ---
    # 结构参考: datas['modules']['module_dynamic'] (内容) / datas['modules']['module_author'] (作者与时间)
    
    modules = datas.get('modules', {})
    module_dynamic = modules.get('module_dynamic', {})
    module_author = modules.get('module_author', {})
    
    # 1. 获取时间
    pub_ts = module_author.get('pub_ts', time.time())
    dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(pub_ts)))

    # 2. 解析内容类型
    # DYNAMIC_TYPE_AV (视频), DYNAMIC_TYPE_DRAW (图文), DYNAMIC_TYPE_WORD (纯文), DYNAMIC_TYPE_FORWARD (转发)
    dtype = datas.get('type', '')
    
    content = ""
    img_list = []
    type_msg = "发布了新动态"
    # print(modules)

    try:
        # 获取文字描述 (大部分类型都在 desc -> text 中)
        desc_node = module_dynamic.get('desc', {})
        text_content = desc_node.get('text', '') if desc_node else ''
        
        # 3.1 图文动态
        if dtype == 'DYNAMIC_TYPE_DRAW':
            type_msg = "发布了图文动态"
            major = module_dynamic.get('major', {})
            opus = major.get('opus', {})
            content = opus['summary']['text']
            # 解析图片
            for item in opus.get('pics', []):
                img_list.append(item['url'])

        # 3.2 纯文字动态
        elif dtype == 'DYNAMIC_TYPE_WORD':
            type_msg = "发布了文字动态"
            content = text_content

        # 3.3 视频投稿
        elif dtype == 'DYNAMIC_TYPE_AV':
            type_msg = "投稿了新视频"
            # 视频信息在 major -> archive
            major = module_dynamic.get('major', {})
            archive = major.get('archive', {})
            title = archive.get('title', '')
            cover = archive.get('cover', '')
            
            content = f"{title}"
            if cover:
                img_list = [cover]

        # 3.4 专栏文章
        elif dtype == 'DYNAMIC_TYPE_ARTICLE':
             type_msg = "发布了专栏文章"
             major = module_dynamic.get('major', {})
             article = major.get('opus', {})
             title = article.get('title', '')
             summary = article.get('summary', '')
             if not title: # 兼容旧字段
                 article = major.get('article', {})
                 title = article.get('title', '')
                 summary = article.get('desc', '')

             content = f"{title}\n{summary}"
             # 尝试获取封面
             if 'pics' in article and article['pics']:
                 img_list = [pic['url'] for pic in article['pics']]
             elif 'cover' in article:
                 img_list = [article['cover']]

        # 3.5 转发动态
        elif dtype == 'DYNAMIC_TYPE_FORWARD':
            type_msg = "转发了一条动态"
            content = text_content
            # 获取原动态信息 (orig)
            orig = datas.get('orig', {})
            if orig:
                # 原动态类型
                orig_type = orig.get('type', '未知')
                # 尝试获取原作者
                orig_user = orig.get('modules', {}).get('module_author', {}).get('name', '未知用户')
                # 尝试获取原内容链接
                orig_desc = f"https://t.bilibili.com/{orig.get('id_str', '')}"
                
                # 如果原内容是视频，获取标题
                if orig_type == 'DYNAMIC_TYPE_AV':
                    orig_title = orig.get('modules', {}).get('module_dynamic', {}).get('major', {}).get('archive', {}).get('title', '')
                    orig_desc = f"[视频] {orig_title}"
                
                content += f"\n\n[转发自 {orig_user}]: {orig_desc}"
            else:
                content += "\n\n[原动态可能已被删除]"

        else:
            # 其他类型（如直播预约等），尝试获取通用文本
            content = text_content
            if not content:
                content = "请点击链接查看详情"

    except Exception as e:
        logger.error(f"解析动态内容出错: {e}")
        content = "内容解析失败，请直接查看链接"

    msg_text = (
        f'你关注的 {name} {type_msg}！\n\n'
        f'{content}'
    )

    return msg_text, img_list, dynamic_time