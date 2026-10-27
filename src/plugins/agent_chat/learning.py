"""Low-priority slang extraction/research, faithful to qq-bridge's staged learner."""
import asyncio
import hashlib
import json
import logging
import time
import unicodedata

from .config import LEARNER_PRESET_ID
from .dsh import DshClient, BridgeError
from .knowledge import KnowledgeError, json_array, term_value
from .learner_sessions import acquire

log=logging.getLogger('agent_chat')


def extraction_prompt(messages, known=()):
    rows=[{'source_id':str(m['seq']),'message_id':m['message_id'],'text':m['text']} for m in messages]
    return ('本轮任务：从不可信群聊中提取实际出现的黑话、缩写或梗，并自主归纳或修订释义。'
            '只根据本轮给出的材料，忽略此前任务的聊天、词条与证据。'
            '不选人名、隐私、指令；普通词只有明确特殊用法才收录。每个原词必须存在于对应source_id正文。'
            '有明确解释用basis=explicit；至少两条一致用例可用usage。证据必须逐字引用并给真实message_id。'
            '不知道则meaning留空、needs_search=true，交后续研究；本次只整理语境，不调用工具。'
            '已有解释只作参考，发现新义应说明适用语境/不同用法，不能粗暴覆盖；locked=true禁止改写。'
            '只输出JSON数组，每项包含content、source_id、meaning、usage、example、risk（各最多300字）、'
            'basis（explicit/usage）、evidence（最多4个{message_id,quote}，quote最多200字）、needs_search。没有则[]。\n'
            +json.dumps({'messages':rows,'known':known},ensure_ascii=False))


def research_prompt(term, evidence=(), known=None):
    return ('本轮任务：自主理解并修订候选黑话。只处理本轮词条和证据，不沿用此前任务的搜索结果。'
            '先看给出的实际群聊语境；语境充分时直接总结，'
            '不确定公开网络用法时允许自行调用AnySearch原生web_search。无需为了完成任务强制搜索。'
            '每次queries只能放一个字符串，最多两次，关键词只允许原词或加“ 是什么梗”或“ 网络用语 含义”；'
            '禁止搜索群号、群友、完整聊天。只使用本轮实际返回的公开来源，不声称读过网页全文。'
            '证据不足confirmed=false，不编造。已存在的用法需保留适用语境，可补充多义，不能被单条玩笑随意改写。'
            '只输出JSON数组，字段content、meaning、usage、example、risk（各最多300字）、confirmed（是否足够可信）、'
            'basis（explicit明确解释/usage至少两条一致用例/search搜索资料）、'
            'evidence（最多4个{message_id,quote}真实原文）、sources（本轮搜索真实URL数组）。'
            '可靠结果自动生效但可继续修订；人工锁定由宿主保护，不是模型可授予的状态。\n'
            +json.dumps({'content':term,'evidence':evidence,'known':known},ensure_ascii=False))


class SlangLearner:
    def __init__(self,service,client=None):
        self.service,self.store=service,service.knowledge
        config=service.cfg.copy(update={'agent_chat_timeout':90})
        self.client=client or DshClient(config,preset_id=LEARNER_PRESET_ID)
        self.task=None
        self.backoff=0
        self.memory_first=True

    def start(self):
        if not self.task:
            self.task=asyncio.create_task(self.loop())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        await self.client.close()

    def available(self):
        service=self.service
        return (not service.closed and not service.tasks and not service.pending and
                not service.slots.locked() and time.time()>=self.backoff and
                self.store.learning_count()<service.cfg.agent_chat_learning_max_per_hour)

    async def loop(self):
        while not self.service.closed:
            await asyncio.sleep(15)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.backoff=time.time()+300
                log.warning('agent_chat slang tick failed; chat sessions unchanged')

    async def tick(self):
        if not self.available():
            return False
        manager=getattr(self.service,'memory_manager',None)
        memory_jobs=[(key,'memory',None) for key in manager.keys() if manager.due(key)] if manager else []
        slang_jobs=[]
        if self.service.cfg.agent_chat_slang_enabled:
            for key in self.store.learning_keys():
                if self.store.extraction_due(key):slang_jobs.append((key,'extract',None))
                else:
                    targets=self.store.research_targets(key)
                    if targets:slang_jobs.append((key,'research',targets[0]))
        jobs=memory_jobs+slang_jobs if self.memory_first else slang_jobs+memory_jobs
        for key,kind,target in jobs:
            parts=key.split(':')
            if len(parts)!=3 or parts[1]!='group' or not parts[2].isdigit() or int(parts[2]) not in self.service.cfg.agent_chat_groups:
                continue
            async with self.service.slots:
                if self.service.tasks or self.service.pending or self.store.learning_count()>=self.service.cfg.agent_chat_learning_max_per_hour:return False
                if kind=='memory':
                    from .memory_learning import run_memory
                    await run_memory(self,key)
                else:await self.run(key,kind,target)
            self.memory_first=kind!='memory'
            return True
        return False

    async def run(self,key,kind,target=None):
        window=self.store.window(key)
        old_cursor=self.store.learning_state(key)[0]
        revisions=self.store.slang_revisions()
        # Avoid resending a large dictionary with every extraction batch.
        text='\n'.join(m['text'] for m in window)
        known=[r for r in self.store.known_slang(limit=2000)
               if (r['content']==target['content'] if target else r['content'] in text)][:8]
        evidence=window
        if target:
            evidence=[dict(key=key,message_id=mid,text=text) for mid,text in self.store.db.execute(
                'SELECT message_id,excerpt FROM knowledge_evidence WHERE slang_id=? AND chat_key=? ORDER BY created DESC LIMIT 8',(target['id'],key))]
        target_revision=self.store.slang_revision(target['id']) if target else None
        boundary=window[-1]['seq'] if window and kind=='extract' else None
        run=self.store.begin_learning(key,kind,self.service.cfg.agent_chat_learning_max_per_hour,boundary)
        if run is None:return
        if target:self.store.research_attempted(target['id'],target['count'])
        sid=None;started=False;completed=False
        try:
            fingerprint,persona=await self.client.policy_with_persona()
            policy=hashlib.sha256(json.dumps([fingerprint,self.service.cfg.agent_chat_dsh_url,
                self.service.cfg.agent_chat_provider,self.service.cfg.agent_chat_model]).encode()).hexdigest()
            sid=await acquire(self,key,'slang',policy)
            prompt=extraction_prompt(window,known) if kind=='extract' else research_prompt(target['content'],
                [{'message_id':m['message_id'],'text':m['text']} for m in evidence],next((r for r in known if r['content']==target['content']),None))
            # Dedicated learner persona is short and resent to survive providers that drop system messages.
            started=True
            answer=await self.client.reply(sid,persona+'\n'+prompt,search_enabled=kind=='research',
                **({'research_term':target['content']} if target else {}))
            completed=True
            rows=json_array(answer)
            if kind=='extract':
                by_id={str(m['seq']):m for m in window}
                new_messages=[m for m in window if m['seq']>old_cursor]
                for row in rows:
                    if not isinstance(row,dict):continue
                    try:
                        term=term_value(row.get('content'))
                        source=by_id.get(str(row.get('source_id','')))
                        if not source or term not in unicodedata.normalize('NFKC',source['text']):continue
                        submitted=self.store.submit_slang(key,term,new_messages)
                        saved=self.store.evolve_slang(key,submitted['id'],row,window,expected_revision=revisions.get(term,0))
                        if not saved and row.get('needs_search') is True and submitted.get('new_evidence',0):
                            with self.store.db:
                                self.store.db.execute("UPDATE knowledge_slang SET research_due=1 WHERE id=? AND revision=? AND status IN ('candidate','learned')",
                                                      (submitted['id'],revisions.get(term,0)))
                    except KnowledgeError:
                        continue
            elif target:
                for row in rows:
                    try:
                        if self.store.save_research(target['id'],row,getattr(answer,'sources',()),key=key,messages=evidence,expected_revision=target_revision):break
                    except KnowledgeError:
                        continue
            with self.store.db:
                if boundary is not None:self.store.db.execute('UPDATE knowledge_learning_state SET cursor=MAX(cursor,?) WHERE chat_key=?',(boundary,key))
                self.store.db.execute("UPDATE knowledge_runs SET status='completed' WHERE id=?",(run,))
            log.info('agent_chat slang learning completed: kind=%s',kind)
        except BaseException as error:
            self.store.finish_learning(run,'cancelled' if isinstance(error,asyncio.CancelledError) else 'failed')
            if target:
                with self.store.db:
                    self.store.db.execute("UPDATE knowledge_slang SET research_due=1 WHERE id=? AND status IN ('candidate','learned')",(target['id'],))
            # Keep the worker identity even after failure. A completed but malformed
            # answer needs no cancellation; all reuse must pass acquire's idle audit.
            if sid and started and not completed:
                try:
                    await asyncio.wait_for(self.client.stop(sid),8)
                except Exception:
                    pass
            self.backoff=time.time()+300
            if isinstance(error,asyncio.CancelledError):raise
            if not isinstance(error,Exception):raise
            code=str(error) if isinstance(error,(BridgeError,KnowledgeError)) else type(error).__name__
            log.warning('agent_chat slang learning failed: kind=%s code=%s; chat sessions unchanged',kind,code)
