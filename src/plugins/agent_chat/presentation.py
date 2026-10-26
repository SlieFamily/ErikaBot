"""Small, explicitly allowed QQ output vocabulary; never interpret arbitrary CQ."""
import json
import re
import time
from .domain import strip_reasoning

# Verified against the installed NapCat QQ face catalog. No custom image URLs.
FACES = {'撇嘴':1,'得意':4,'流泪':5,'害羞':6,'尴尬':10,'发怒':11,'调皮':12,
         '呲牙':13,'微笑':14,'偷笑':20,'可爱':21,'白眼':22,'傲慢':23,'疑问':32,
         '鄙视':105,'委屈':106,'阴险':108,'笑哭':182,'托腮':212,'捂脸':264,'吃瓜':271}
REACTIONS = {'👍':'128077','😂':'128514','❤️':'10084','捂脸':'264','吃瓜':'271'}
PREFIX = 'QQ_REPLY '


class Outgoing(str):
    def __new__(cls, text, reply_to='', faces=(), mentions=(), reaction=(), poke=''):
        value = super().__new__(cls, text)
        value.reply_to, value.faces = reply_to, tuple(faces)
        value.mentions, value.reaction, value.poke = tuple(mentions), tuple(reaction), poke
        return value

    def __bool__(self):
        return bool(str(self)) or bool(self.faces) or bool(self.mentions) or bool(self.reaction) or bool(self.poke)


def reply_targets(messages, key, now=None):
    now = time.time() if now is None else now
    # Match intake clock-skew tolerance: QQ timestamps may be ahead of this host.
    # Retain the same-chat, bounded-history and 10-minute age restrictions.
    return {str(m.get('message_id')) for m in messages
            if m.get('key') == key and -120 <= now-float(m.get('timestamp',0)) <= 600
            and re.fullmatch(r'-?\d{1,20}',str(m.get('message_id','')))
            and -(2**63) <= int(m['message_id']) < 2**63}


def social_targets(messages, key, config, proactive=False, now=None):
    """Only observed outer messages from recent participants in this group grant targets."""
    scope = {'mentions':set(), 'reaction':set(), 'poke':set()}
    if proactive or ':group:' not in key:
        return scope
    now = time.time() if now is None else now
    valid = reply_targets(messages,key,now)
    bot_id = key.split(':',1)[0]
    records = [m for m in messages if str(m.get('message_id')) in valid and m.get('key')==key
               and re.fullmatch(r'[1-9][0-9]{0,19}',str(m.get('user_id','')))
               and str(m['user_id'])!=bot_id and int(m['user_id'])<2**63]
    users = {str(m['user_id']) for m in records}
    if config.agent_chat_mentions_enabled: scope['mentions'] = users
    if config.agent_chat_poke_enabled: scope['poke'] = users
    if config.agent_chat_reactions_enabled: scope['reaction'] = {str(m['message_id']) for m in records}
    return scope


def instructions(targets, faces=True, social=None):
    scope = social or {'mentions':set(), 'reaction':set(), 'poke':set()}
    return ('\n管理员允许的 QQ 表达方式：普通发言直接写正文，可自然使用 Unicode emoji，少量即可。'
        '你可自行选择引用、QQ表情、@某个群友、给对方消息贴一个表情回应、轻轻戳一下。'
        '按聊天氛围选择，不必等别人要求，不要每句都做；自然有趣、友好，不用互动动作骚扰或催回复。'
        '仅在需要这些动作时，输出 QQ_REPLY 后跟一个 JSON 对象：'
        '{"text":"最终发言","reply_to":"消息ID或空字符串","faces":[],"mentions":[],"reaction":null,"poke":""}。'
        'text 可含emoji；faces最多两个；mentions最多两个本轮允许的QQ号字符串，用于明确接谁的话。'
        'reaction 可为 {"message_id":"本轮消息ID","emoji":"👍"}，是贴到那条消息上的回应，区别于正文表情；'
        'poke填一个允许的QQ号或空字符串。无需动作的字段留空；新增的mentions/reaction/poke字段也可省略。'
        '只贴表情或戳人时text可为空；对实质提问仍应回答，别只戳一下敷衍。'
        '不得编造已执行成功的动作；实际发送由桥接校验，冷却或接口失败时可能跳过。'
        '不要代码围栏、额外字段或CQ码。完全不回应时只输出 [SILENT]，它会取消所有动作。'
        '本轮可引用ID：'+json.dumps(sorted(targets))+'；禁止其他ID、转发内部节点或其他群消息。'
        '可选QQ表情：'+('、'.join(FACES) if faces else '无，faces必须为空')+'。'
        '可贴表情：'+'、'.join(REACTIONS)+'；可贴的消息ID：'+json.dumps(sorted(scope['reaction']))+'。'
        '可@的QQ号：'+json.dumps(sorted(scope['mentions']))+'；可戳的QQ号：'+json.dumps(sorted(scope['poke']))+'。'
        '空列表表示本轮不允许；禁止@全体。戳人和贴表情都有本地冷却，不能连续操作或重复回应同一条消息。\n')


def parse(text, targets, faces=True, social=None):
    value = strip_reasoning(text).strip()
    if 'QQ_REPLY' in text and not value.startswith(PREFIX):
        return Outgoing('')
    if not value.startswith(PREFIX):
        # Partial/misformatted envelopes must not be published as protocol text.
        return Outgoing('' if value.startswith('QQ_REPLY') else value)
    try:
        obj = json.loads(value[len(PREFIX):])
        if not isinstance(obj,dict) or not {'text','reply_to','faces'} <= set(obj) or set(obj)-{'text','reply_to','faces','mentions','reaction','poke'}: raise ValueError()
        if not isinstance(obj['text'],str) or not isinstance(obj['reply_to'],str): raise ValueError()
        if not isinstance(obj['faces'],list) or len(obj['faces'])>2: raise ValueError()
        if any(not isinstance(f,str) for f in obj['faces']): raise ValueError()
        mentions = obj.get('mentions',[])
        reaction = obj.get('reaction')
        poke = obj.get('poke','')
        if not isinstance(mentions,list) or len(mentions)>2 or any(not isinstance(u,str) for u in mentions): raise ValueError()
        if not isinstance(poke,str): raise ValueError()
        if reaction is not None and (not isinstance(reaction,dict) or set(reaction)!={'message_id','emoji'}
                or not all(isinstance(v,str) for v in reaction.values())): raise ValueError()
        if strip_reasoning(obj['text']).strip() == '[SILENT]': return Outgoing('[SILENT]')
        scope = social or {'mentions':set(), 'reaction':set(), 'poke':set()}
        selected_faces = [FACES[f] for f in obj['faces'] if faces and f in FACES]
        selected_mentions = list(dict.fromkeys(u for u in mentions if u in scope['mentions'])) if obj['text'].strip() or selected_faces else []
        selected_reaction = ((reaction['message_id'],REACTIONS[reaction['emoji']])
            if reaction and reaction['message_id'] in scope['reaction'] and reaction['emoji'] in REACTIONS else ())
        return Outgoing(obj['text'],obj['reply_to'] if obj['reply_to'] in targets else '',selected_faces,
                        selected_mentions,selected_reaction,poke if poke in scope['poke'] else '')
    except (ValueError,TypeError):
        return Outgoing('')


def segments(value):
    """Only trusted parser attributes create reply/face segments; text stays literal."""
    result=[]
    if isinstance(value,Outgoing) and value.reply_to:
        result.append({'type':'reply','data':{'id':value.reply_to}})
    if isinstance(value,Outgoing):
        for uid in value.mentions:
            result.extend([{'type':'at','data':{'qq':uid}},{'type':'text','data':{'text':' '}}])
    if str(value): result.append({'type':'text','data':{'text':str(value)}})
    if isinstance(value,Outgoing):
        result.extend({'type':'face','data':{'id':str(face)}} for face in value.faces)
    return result
