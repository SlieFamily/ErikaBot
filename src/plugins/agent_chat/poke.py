"""Receive native poke notices without treating them as mandatory questions."""
import hashlib
import random
import re
import time
from .domain import ChatMessage


def poke_message(bot_id,user_id,target_id,group_id,timestamp,history=()):
    if str(target_id)!=str(bot_id) or str(user_id)==str(bot_id):return None
    if not re.fullmatch(r'[1-9]\d{0,19}',str(user_id)) or int(user_id)>=2**63:return None
    stamp=float(timestamp)
    if abs(time.time()-stamp)>120:return None
    key=f'{bot_id}:group:{group_id}' if group_id else f'{bot_id}:private:{user_id}'
    # OneBot poke notices have no message ID. Same sender/target/chat/second is
    # deliberately treated as one notification; it must never become a QQ quote.
    identity=hashlib.sha256(f'{key}:{user_id}:{target_id}:{int(stamp)}'.encode()).hexdigest()
    name=next((m['name'] for m in reversed(history) if m.get('key')==key and m.get('user_id')==str(user_id)),str(user_id))
    return ChatMessage(key,'poke-'+identity,str(user_id),name[:80],
                       '[QQ通知：这位群友戳了戳你]' if group_id else '[QQ通知：对方戳了戳你]',stamp,notice='poke')


def is_poke_record(message):
    return message.get('notice')=='poke' and bool(re.fullmatch(r'poke-[a-f0-9]{64}',str(message.get('message_id',''))))


class PokeGate:
    def __init__(self,store,config):
        self.db,self.cfg=store.db,config
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS poke_notices(chat_key TEXT NOT NULL,event_id TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(chat_key,event_id));
          CREATE TABLE IF NOT EXISTS poke_reply_gate(chat_key TEXT PRIMARY KEY,accepted REAL NOT NULL);
        ''')

    def admit(self,message):
        if not self.cfg.agent_chat_poke_reply_enabled or not is_poke_record(message.payload()):return False
        now=time.time()
        if abs(now-message.timestamp)>120:return False
        with self.db:
            self.db.execute('DELETE FROM poke_notices WHERE created<?',(now-300,))
            self.db.execute('DELETE FROM poke_reply_gate WHERE accepted<?',(now-86400,))
            fresh=self.db.execute('INSERT OR IGNORE INTO poke_notices VALUES(?,?,?)',(message.key,message.message_id,now)).rowcount
            # Limit notification-only data without evicting ordinary chat history.
            self.db.execute('DELETE FROM poke_notices WHERE chat_key=? AND rowid NOT IN '
                '(SELECT rowid FROM poke_notices WHERE chat_key=? ORDER BY created DESC,rowid DESC LIMIT 256)',(message.key,message.key))
            if not fresh:return False
            row=self.db.execute('SELECT accepted FROM poke_reply_gate WHERE chat_key=?',(message.key,)).fetchone()
            if row and now-row[0]<self.cfg.agent_chat_poke_reply_cooldown:return False
            if random.random()>=self.cfg.agent_chat_poke_reply_probability:return False
            self.db.execute('INSERT INTO poke_reply_gate VALUES(?,?) ON CONFLICT(chat_key) DO UPDATE SET accepted=excluded.accepted',(message.key,now))
        return True
