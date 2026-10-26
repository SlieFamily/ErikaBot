"""Event-driven post-send observation: no timer loop, model polling or held semaphore."""
from dataclasses import dataclass,field
import re
import time

_END=re.compile(r'^(?:好[的吧]?[,， ]*)?(?:晚安|拜拜|再见|先下了|不聊了|不用回了|不用回复了|先这样|就这样吧)[!！。~～ ]*$')
def ending(text):return bool(_END.fullmatch(text.strip()))

@dataclass
class Window:
    session_id:str
    generation:int
    until:float
    opened_seq:int
    participants:set=field(default_factory=set)
    anchors:set=field(default_factory=set)
    calls:int=0

class ReplyObserver:
    def __init__(self,config,store):self.cfg,self.store,self.windows,self.serial=config,store,{},0
    def get(self,key):
        row=self.windows.get(key)
        if row and (time.monotonic()>=row.until or not self.cfg.agent_chat_observation_enabled):
            self.windows.pop(key,None);return None
        return row
    def close(self,key):self.windows.pop(key,None)
    def clear(self):self.windows.clear()
    def opened(self,key,sid,messages,answer,kind):
        if not self.cfg.agent_chat_observation_enabled or ':group:' not in key:return
        if ending(str(answer)) or any(ending(m.text) for m in messages):self.close(key);return
        users={m.user_id for m in messages if m.user_id.isdigit() and m.user_id!=key.split(':')[0]}
        users.update(getattr(answer,'mentions',()))
        anchors={m.message_id for m in messages if m.message_id}
        sent=getattr(answer,'sent_message_id','')
        if sent:anchors.add(sent)
        previous=self.get(key)
        if kind=='followup':
            if previous and previous.session_id==sid:
                previous.participants.update(users);previous.anchors=set(list(previous.anchors|anchors)[-20:])
            return  # Never restart the observation budget after its own followup.
        self.serial+=1
        boundary=self.store.db.execute('SELECT COALESCE(MAX(seq),0) FROM messages WHERE chat_key=?',(key,)).fetchone()[0]
        self.windows[key]=Window(sid,self.serial,time.monotonic()+self.cfg.agent_chat_observation_seconds,boundary,users,anchors)
    def offer(self,message):
        row=self.get(message.key)
        if not row:return None
        bound=self.store.session(message.key)
        if not bound or bound[0]!=row.session_id or bound[2]:self.close(message.key);return None
        related=message.user_id in row.participants or bool(message.reply_to and message.reply_to in row.anchors)
        if not related:return None
        if ending(message.text):self.close(message.key);return None
        if row.calls>=self.cfg.agent_chat_observation_max_calls:return None
        seq=self.store.db.execute('SELECT seq FROM messages WHERE chat_key=? AND message_id=?',(message.key,message.message_id)).fetchone()
        if not seq or seq[0]<=row.opened_seq:return None
        return row.generation
    def claim(self,message,generation):
        row=self.get(message.key)
        if not row or self.offer(message)!=generation:return False
        delivered=self.store.delivery(message.key,row.session_id)
        seq=self.store.db.execute('SELECT seq FROM messages WHERE chat_key=? AND message_id=?',(message.key,message.message_id)).fetchone()[0]
        if delivered and seq<=delivered[0]:return False
        row.calls+=1
        return True
    def describe(self,key):
        row=self.get(key)
        if not self.cfg.agent_chat_observation_enabled:return '发送后观察：关闭'
        if not row:return '发送后观察：待下次成功发言后开启'
        return f'发送后观察：剩余约{max(0,int(row.until-time.monotonic()))}秒；无@续聊判断{row.calls}/{self.cfg.agent_chat_observation_max_calls}'
