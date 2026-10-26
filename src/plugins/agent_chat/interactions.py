"""Optional social actions through NoneBot's existing factories and Bot API dispatch."""
import asyncio
import logging
from .presentation import Outgoing, REACTIONS, segments, social_targets

log = logging.getLogger('agent_chat')


def qq_message(value):
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
    message = Message()
    for row in segments(value):
        data = row['data']
        if row['type'] == 'reply': message += MessageSegment.reply(data['id'])
        elif row['type'] == 'at': message += MessageSegment.at(data['qq'])
        elif row['type'] == 'face': message += MessageSegment.face(int(data['id']))
        elif row['type'] == 'text': message += MessageSegment.text(data['text'])
    return message


class SocialActions:
    def __init__(self, config, store):
        self.config, self.store = config, store

    async def _attempt(self, key, kind, target, cooldown, call):
        try:
            if not self.store.reserve_interaction(key,kind,target,cooldown): return False
            result = await asyncio.wait_for(call(),6)
            status = result.get('result') if isinstance(result,dict) else None
            # NapCat returns numeric 0 on success; other adapters may return bool.
            if status is False or (type(status) is int and status != 0):
                log.warning('agent_chat optional interaction rejected: kind=%s',kind)
                return False
            return True
        except asyncio.CancelledError:
            raise
        except Exception as error:
            info = getattr(error,'info',{})
            code = info.get('retcode') if isinstance(info,dict) else None
            log.warning('agent_chat optional interaction failed: kind=%s error=%s retcode=%s',kind,type(error).__name__,code)
            return False

    async def send(self, bot, key, value, send_message):
        if not isinstance(value,Outgoing):
            await send_message(value)
            return True
        # Recheck after model latency: stale/evicted targets, disabled features and
        # another bot/group cannot inherit permissions from an earlier prompt.
        parts = key.split(':')
        group = (int(parts[2]) if len(parts)==3 and parts[0]==str(bot.self_id)
                 and parts[1]=='group' and parts[2].isdigit() else None)
        scope = (social_targets(self.store.recent(key,200),key,self.config)
                 if group in self.config.agent_chat_groups else {'mentions':set(),'reaction':set(),'poke':set()})
        mentions = tuple(u for u in value.mentions if u in scope['mentions'])[:2]
        reaction = (value.reaction if len(value.reaction)==2 and value.reaction[0] in scope['reaction']
                    and value.reaction[1] in REACTIONS.values() else ())
        poke = value.poke if value.poke in scope['poke'] else ''
        body = Outgoing(str(value),value.reply_to,value.faces,mentions if str(value) or value.faces else ())
        sent = False
        if segments(body):
            receipt=await send_message(body)
            if isinstance(receipt,dict) and str(receipt.get('message_id','')).lstrip('-').isdigit():
                value.sent_message_id=str(receipt['message_id'])
            sent = True
        # These are public OneBot extension actions sent through the installed Bot.
        # No HTTP client, packet construction, raw CQ or model-selected API names.
        if reaction:
            mid, emoji = reaction
            ok = await self._attempt(key,'reaction',mid,self.config.agent_chat_reaction_cooldown,
                lambda: bot.set_msg_emoji_like(message_id=int(mid),emoji_id=emoji,set=True,_timeout=5))
            sent = ok or sent
        if poke:
            ok = await self._attempt(key,'poke',poke,self.config.agent_chat_poke_cooldown,
                lambda: bot.group_poke(group_id=group,user_id=int(poke),_timeout=5))
            sent = ok or sent
        return sent
