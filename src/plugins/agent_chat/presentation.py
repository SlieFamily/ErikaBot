"""Small, explicitly allowed QQ output vocabulary; never interpret arbitrary CQ."""
import json
import re
import time
from .domain import strip_reasoning

# Verified against the installed NapCat QQ face catalog. No custom image URLs.
FACES = {'撇嘴':1,'得意':4,'流泪':5,'害羞':6,'尴尬':10,'发怒':11,'调皮':12,
         '呲牙':13,'微笑':14,'偷笑':20,'可爱':21,'白眼':22,'傲慢':23,'疑问':32,
         '鄙视':105,'委屈':106,'阴险':108,'笑哭':182,'托腮':212,'捂脸':264,'吃瓜':271}
PREFIX = 'QQ_REPLY '


class Outgoing(str):
    def __new__(cls, text, reply_to='', faces=()):
        value = super().__new__(cls, text)
        value.reply_to, value.faces = reply_to, tuple(faces)
        return value

    def __bool__(self):
        return bool(str(self)) or bool(self.faces)


def reply_targets(messages, key, now=None):
    now = time.time() if now is None else now
    return {str(m.get('message_id')) for m in messages
            if m.get('key') == key and 0 <= now-float(m.get('timestamp',0)) <= 600
            and re.fullmatch(r'-?\d{1,20}',str(m.get('message_id','')))
            and -(2**63) <= int(m['message_id']) < 2**63}


def instructions(targets, faces=True):
    return ('\n管理员允许的 QQ 表达方式：普通发言直接写正文，可自然使用 Unicode emoji，少量即可。'
        '想明确回应某条消息时可自主选择引用；想使用 QQ 自带表情时可选择下列名称，不要每句都加。'
        '仅在需要引用或 QQ 表情时，输出 QQ_REPLY 后跟一个 JSON 对象：'
        '{"text":"最终发言","reply_to":"消息ID或空字符串","faces":["捂脸"]}。'
        'text 可含 emoji；faces 最多两个，也可为空；不要代码围栏、额外字段或 CQ 码。'
        '只发表情时 text 可为空。沉默仍只输出 [SILENT]。'
        '本轮可引用的真实消息ID：'+json.dumps(sorted(targets))+'；禁止引用其他ID、转发内部节点或其他群消息。'
        '可选QQ表情：'+('、'.join(FACES) if faces else '无，本轮 faces 必须为空')+'。\n')


def parse(text, targets, faces=True):
    value = strip_reasoning(text).strip()
    if 'QQ_REPLY' in text and not value.startswith(PREFIX):
        return Outgoing('')
    if not value.startswith(PREFIX):
        # Partial/misformatted envelopes must not be published as protocol text.
        return Outgoing('' if value.startswith('QQ_REPLY') else value)
    try:
        obj = json.loads(value[len(PREFIX):])
        if not isinstance(obj,dict) or set(obj) != {'text','reply_to','faces'}: raise ValueError()
        if not isinstance(obj['text'],str) or not isinstance(obj['reply_to'],str): raise ValueError()
        if not isinstance(obj['faces'],list) or len(obj['faces'])>2: raise ValueError()
        if any(not isinstance(f,str) for f in obj['faces']): raise ValueError()
        if strip_reasoning(obj['text']).strip() == '[SILENT]': return Outgoing('[SILENT]')
        return Outgoing(obj['text'],obj['reply_to'] if obj['reply_to'] in targets else '',
                        [FACES[f] for f in obj['faces'] if faces and f in FACES])
    except (ValueError,TypeError):
        return Outgoing('')


def segments(value):
    """Only trusted parser attributes create reply/face segments; text stays literal."""
    result=[]
    if isinstance(value,Outgoing) and value.reply_to:
        result.append({'type':'reply','data':{'id':value.reply_to}})
    if str(value): result.append({'type':'text','data':{'text':str(value)}})
    if isinstance(value,Outgoing):
        result.extend({'type':'face','data':{'id':str(face)}} for face in value.faces)
    return result
