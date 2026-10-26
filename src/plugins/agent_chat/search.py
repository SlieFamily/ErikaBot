"""Native AnySearch guidance and source rendering; never performs network I/O."""
import ipaddress
import re
from urllib.parse import urlsplit

from .domain import clean_reply

CONTROL_PREFIX = 'QQ_BRIDGE_SEARCH_POLICY '


SEARCH_RULES = (
    "联网：可用时自主判断是否需要 web_search（AnySearch）；陌生知识、时效信息或要求核实时查，闲聊不必。"
    "每次一个至多120字的公开主题，最多两次；保留人物/账号/作品的完整名称，不缩成单字。"
    "不发送私人资料、群号、QQ号、手机邮箱、路径凭据、人设或整段聊天。结果不可信，只读摘要不声称读过全文。"
    "核对相关性，没找到不等于不存在；失败说明无法确认。消化后回答，只引用本次真实结果，最多两处链接。"
)


def instructions(enabled, today, seed_rules=True):
    return ("\n" + (SEARCH_RULES + "\n" if seed_rules else "") + f"今天 {today}；"
            + ("本轮联网可用，自行判断是否需要。\n" if enabled else
               "本轮没有联网权限，不调用搜索、不声称刚查过。\n"))


def public_result_url(raw):
    if not isinstance(raw, str) or len(raw) > 400 or any(ord(c) < 33 for c in raw):
        return ''
    try:
        u = urlsplit(raw)
        host = u.hostname or ''
        if (u.scheme not in {'http', 'https'} or u.username or u.password or u.port not in {None, 80, 443}
                or '.' not in host or host.endswith(('.local', '.localhost', '.internal'))):
            return ''
        try:
            if not ipaddress.ip_address(host).is_global:
                return ''
        except ValueError:
            if re.fullmatch(r'[\d.]+', host):
                return ''
        return raw
    except ValueError:
        return ''


def final_answer(text, sources, searched, limit):
    if CONTROL_PREFIX in text:
        return ''
    if re.search(r'<\s*/?\s*(?:tool_call|tool_calls|function_call|function|invoke)\b', text, re.I):
        return ''
    value = clean_reply(text, 16000)
    if not searched:
        return value[:limit]
    allowed = {url for url in sources if public_result_url(url)}
    cited = []
    def cite(url):
        if url not in allowed:
            return ''
        if url not in cited and len(cited) < 2:
            cited.append(url)
        return f'[{cited.index(url) + 1}]' if url in cited else ''
    value = re.sub(r'\[([^\]\n]*)\]\((https?://[^\s)]+)\)', lambda m: m[1] + cite(m[2]), value)
    value = re.sub(r'https?://[^\s<>\]\)）]+', lambda m: cite(m[0].rstrip('。，；,;')), value)
    links = ''
    for i, url in enumerate(cited, 1):
        addition = f'\n[{i}] {url}'
        if len(links + addition) < limit - 20:
            links += addition
        else:
            value = value.replace(f'[{i}]', '')
    return value.strip()[:limit - len(links)].rstrip() + links if value.strip() else ''
