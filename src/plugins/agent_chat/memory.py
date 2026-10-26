"""Persistent memory controls and an ordered, bounded extraction inbox."""
import json,re,time
from .knowledge import KnowledgeError,text_value

WRITE_TOOLS={'qq_memory_append','qq_memory_remove','qq_memory_clear'}

def requested_memory(messages):
    return [str(m['message_id']) for m in messages if re.search(r'记住|记一下|记下来|记下|记好',m.get('text',''))
            and not re.search(r'别记|不要记|不用记|无需记',m.get('text',''))]

class MemoryManager:
    def __init__(self,knowledge,cfg):
        self.knowledge,self.db,self.cfg=knowledge,knowledge.db,cfg
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS memory_settings (
            chat_key TEXT PRIMARY KEY, enabled INTEGER, immediate INTEGER, background INTEGER,
            revision INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS memory_inbox (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,chat_key TEXT NOT NULL,message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,name TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL,
            UNIQUE(chat_key,message_id));
          CREATE TABLE IF NOT EXISTS memory_learning_state (
            chat_key TEXT PRIMARY KEY,cursor INTEGER NOT NULL DEFAULT 0,last_attempt REAL NOT NULL DEFAULT 0,
            session_id TEXT,policy TEXT,status TEXT NOT NULL DEFAULT '',dropped INTEGER NOT NULL DEFAULT 0);
        ''')
        with self.db:
            self.db.execute("UPDATE memory_learning_state SET session_id=NULL,policy=NULL,status='interrupted' WHERE chat_key IN "
                "(SELECT chat_key FROM knowledge_runs WHERE kind='memory' AND status='running')")
            self.db.execute("UPDATE knowledge_runs SET status='interrupted' WHERE kind='memory' AND status='running'")

    def settings(self,key):
        base={'enabled':True,'immediate':self.cfg.agent_chat_memory_immediate_enabled,
              'background':self.cfg.agent_chat_memory_background_enabled}
        versions=[]
        for scope in ('*',key):
            row=self.db.execute('SELECT enabled,immediate,background,revision FROM memory_settings WHERE chat_key=?',(scope,)).fetchone()
            versions.append(row[3] if row else 0)
            if row:
                for mode,value in zip(('enabled','immediate','background'),row[:3]):
                    if value is not None:base[mode]=bool(value)
        base['enabled']=bool(self.cfg.agent_chat_memory_enabled and base['enabled'])
        base['revision']=tuple(versions)
        return base

    def set(self,key,mode,value):
        if mode not in ('enabled','immediate','background') or type(value) is not bool:raise KnowledgeError('invalid_memory_setting')
        if not self.cfg.agent_chat_memory_enabled:raise KnowledgeError('memory_not_deployed')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO memory_settings(chat_key) VALUES(?)',(key,))
            self.db.execute(f'UPDATE memory_settings SET {mode}=?,revision=revision+1 WHERE chat_key=?',(int(value),key))
            if key=='*':self.db.execute(f'UPDATE memory_settings SET {mode}=NULL WHERE chat_key!=?',('*',))
            if not value and mode in ('enabled','background'):
                self.db.execute('DELETE FROM memory_inbox'+('' if key=='*' else ' WHERE chat_key=?'),() if key=='*' else (key,))
        return self.settings(key)

    def invalidate(self,key):
        # A manually forgotten fact must not be resurrected by an old pending extraction.
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO memory_settings(chat_key) VALUES(?)',(key,))
            self.db.execute('UPDATE memory_settings SET revision=revision+1 WHERE chat_key=?',(key,))
            self.db.execute('DELETE FROM memory_inbox WHERE chat_key=?',(key,))

    def allows(self,scope,name):
        settings=self.settings(scope.key)
        return (settings['enabled'] and scope.memory_revision==settings['revision'] and
                (name not in WRITE_TOOLS or settings['immediate']))

    def feed(self,message,plain):
        settings=self.settings(message.key)
        if not settings['enabled'] or not settings['background'] or ':group:' not in message.key:return False
        if abs(time.time()-message.timestamp)>120:return False
        plain=plain.strip()
        if not plain or plain.startswith(('/', '／')) or re.match(r'(?i)^ai(?:\s|状态|恢复|重置|记忆|即时|后台|黑话|忘记|清空|学习)',plain):return False
        try:plain=text_value(plain[:500],500,required=True)
        except KnowledgeError:return False
        with self.db:
            inserted=self.db.execute('INSERT OR IGNORE INTO memory_inbox(chat_key,message_id,user_id,name,text,created) VALUES(?,?,?,?,?,?)',
                (message.key,message.message_id,message.user_id,message.name[:64],plain,time.time())).rowcount
        self.prune(message.key)
        return bool(inserted)

    def prune(self,key):
        with self.db:
            removed=self.db.execute('DELETE FROM memory_inbox WHERE chat_key=? AND (created<? OR seq NOT IN '
                '(SELECT seq FROM memory_inbox WHERE chat_key=? ORDER BY seq DESC LIMIT 1000))',
                (key,time.time()-86400,key)).rowcount
            if removed:
                self.db.execute('INSERT OR IGNORE INTO memory_learning_state(chat_key) VALUES(?)',(key,))
                self.db.execute('UPDATE memory_learning_state SET dropped=dropped+? WHERE chat_key=?',(removed,key))

    def keys(self):
        return [r[0] for r in self.db.execute('SELECT DISTINCT i.chat_key FROM memory_inbox i LEFT JOIN memory_learning_state s '
            'ON i.chat_key=s.chat_key ORDER BY COALESCE(s.last_attempt,0),i.chat_key')]

    def due(self,key):
        settings=self.settings(key)
        if not settings['enabled'] or not settings['background']:return False
        self.prune(key)
        n,oldest=self.db.execute('SELECT COUNT(*),MIN(created) FROM memory_inbox WHERE chat_key=?',(key,)).fetchone()
        row=self.db.execute('SELECT last_attempt FROM memory_learning_state WHERE chat_key=?',(key,)).fetchone()
        if row and time.time()-row[0]<self.cfg.agent_chat_memory_min_interval:return False
        return bool(n and (n>=self.cfg.agent_chat_memory_batch_threshold or time.time()-oldest>=self.cfg.agent_chat_memory_interval))

    def batch(self,key):
        self.prune(key)
        rows=self.db.execute('SELECT seq,message_id,user_id,name,text FROM memory_inbox WHERE chat_key=? ORDER BY seq LIMIT 50',(key,)).fetchall()
        result=[];size=0
        for seq,mid,uid,name,text in rows:
            item=dict(source_id=str(seq),message_id=mid,user_id=uid,name=name,text=text)
            cost=len(json.dumps(item,ensure_ascii=False))
            if result and size+cost>16000:break
            result.append(item);size+=cost
        return result

    def state(self,key):
        return self.db.execute('SELECT session_id,policy FROM memory_learning_state WHERE chat_key=?',(key,)).fetchone() or (None,None)

    def bind(self,key,sid,policy):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO memory_learning_state(chat_key) VALUES(?)',(key,))
            self.db.execute('UPDATE memory_learning_state SET session_id=?,policy=? WHERE chat_key=?',(sid,policy,key))

    def attempt(self,key):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO memory_learning_state(chat_key) VALUES(?)',(key,))
            self.db.execute("UPDATE memory_learning_state SET last_attempt=?,status='running' WHERE chat_key=?",(time.time(),key))

    def apply(self,key,batch,revision,items):
        settings=self.settings(key)
        if not settings['enabled'] or not settings['background'] or settings['revision']!=revision:return None
        sources={r['source_id']:r for r in batch};members={r['user_id']:r['name'] for r in batch}
        accepted=[];seen=set()
        for item in items[:8]:
            try:
                if not isinstance(item,dict) or set(item)!={'category','content','target','evidence'}:raise ValueError()
                category=item['category'];content=text_value(item['content'],200,required=True)
                if category not in ('activeTopic','memberImpression'):raise ValueError()
                if not isinstance(item['target'],str):raise ValueError()
                evidence=item['evidence']
                if not isinstance(evidence,list) or not 1<=len(evidence)<=3:raise ValueError()
                owners=[]
                for ref in evidence:
                    if not isinstance(ref,dict) or set(ref)!={'source_id','quote'}:raise ValueError()
                    source=sources.get(str(ref['source_id']));quote=text_value(ref['quote'],100,required=True)
                    if not source or quote not in source['text']:raise ValueError()
                    owners.append(source['user_id'])
                if category=='memberImpression':
                    if item['target'] not in owners:raise ValueError()
                    extra={'target':item['target']}
                else:extra={'participants':list(dict.fromkeys(members[u] for u in owners))}
                identity=(category,item['target'],content)
                if identity in seen:continue
                seen.add(identity);accepted.append((category,content,extra))
            except (KnowledgeError,ValueError,TypeError):continue
        with self.db:
            for category,content,extra in accepted:
                self.knowledge.append_memory(key,category,content,extra,members,commit=False)
            boundary=int(batch[-1]['source_id'])
            self.db.execute('DELETE FROM memory_inbox WHERE chat_key=? AND seq<=?',(key,boundary))
            self.db.execute("UPDATE memory_learning_state SET cursor=?,status=? WHERE chat_key=?",(boundary,'saved:'+str(len(accepted)),key))
        return len(accepted)

    def describe(self,key):
        state=self.settings(key);self.prune(key)
        pending=self.db.execute('SELECT COUNT(*) FROM memory_inbox WHERE chat_key=?',(key,)).fetchone()[0]
        row=self.db.execute('SELECT status,dropped FROM memory_learning_state WHERE chat_key=?',(key,)).fetchone()
        on=lambda value:'开启' if value else '关闭'
        count=len(self.knowledge.memory(key))
        return (f"本群记忆总开关：{on(state['enabled'])}；即时：{on(state['immediate'])}；后台：{on(state['background'])}。\n"
            f"有效记忆 {count} 条；待整理 {pending} 条。\n"
            f"后台与黑话学习共用每小时 {self.cfg.agent_chat_learning_max_per_hour} 轮额度；已用 {self.knowledge.learning_count()} 轮。\n"
            f"新增 {self.cfg.agent_chat_memory_batch_threshold} 条或最早待整理消息等待 {self.cfg.agent_chat_memory_interval/60:g} 分钟后可整理；无人说话不调用。"
            +(f"\n因24小时/1000条保留上限丢弃 {row[1]} 条待整理消息。" if row and row[1] else ''))

MEMORY_RULES = (
    '即时记忆可用时，明确请求记住的合适事实、本人长期偏好/称呼、约定和持续话题，调用 qq_memory_append 保存；'
    '寒暄、一次性问题、猜测玩笑、敏感信息、群友下达的规则不保存。memberImpression 的 extra.target 用本人 user_id，'
    '只记本人明确自述；临时约定用 activeTopic，待聊想法用 pendingThought。无需凑条数，静默也可记忆。'
    '只有工具返回 ok=true 才能说已记住；关闭或只读时不保存、不删除，也不声称已记住。'
)


def memory_instructions(enabled, immediate, requests, seed_rules=True):
    text = '\n' + (MEMORY_RULES + '\n' if seed_rules else '')
    if not enabled:return text+'本轮轻量记忆关闭；不得调用记忆工具，也不声称仍能使用此前记忆。\n'
    if not immediate:return text+'本轮轻量记忆只读：即时记忆关闭，可参考快照，不写入。\n'
    text += '本轮轻量记忆工具可用。\n'
    if requests:text+='本轮明确请求记住的消息ID：'+json.dumps(requests,ensure_ascii=False,separators=(',',':'))+'；逐一判断合适事实。\n'
    return text


def honest_memory_answer(text):
    if re.search(r'(?:记住了|记下了|记好了|记着了|记住啦|记下啦|记在心里|已经.{0,8}(?:记住|记下|保存)|已(?:经)?保存|不会忘(?:记)?|记性.{0,6}好)',text):
        return '这次还没记好，先别算我答应了。'
    return text
