"""Exercise NoneBot 2's real dispatch against their_ana in a temporary DB directory."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        Path("db").mkdir()
        import nonebot
        nonebot.init(_env_file=None, driver="~fastapi", superusers={"1"}, command_start={"/", ""}, log_level="ERROR")
        from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message, MessageSegment, PokeNotifyEvent, PrivateMessageEvent
        from nonebot.adapters.onebot.v11.bot import _check_reply, _check_at_me
        from nonebot.message import handle_event
        ai_plugin = nonebot.load_plugin("src.plugins.agent_chat")
        ana_plugin = nonebot.load_plugin("src.plugins.their_ana")
        assert ai_plugin and ana_plugin, "plugins must load"
        ai, ana = ai_plugin.module, ana_plugin.module
        ai.config.agent_chat_takeover_mentions = True
        ai.config.agent_chat_slang_enabled = True
        ai.config.agent_chat_groups = frozenset({42})

        class FakeService:
            def __init__(self):
                from src.plugins.agent_chat.interactions import SocialActions
                self.observed = []; self.scheduled = []; self.poked=[]; self.recovered=[]; self.learned=[]; self.knowledge=None
                self.store=ai.Store(Path(td)/'social.sqlite3'); self.social=SocialActions(ai.config,self.store)
            def allowed(self, bot_id, group_id, user_id): return group_id == 42 and str(user_id) != str(bot_id)
            def observe(self, message): self.observed.append(message); self.store.append(message); return True
            def schedule(self, message, send, prepare=None): self.scheduled.append((message, send)); self.prepare = prepare
            def schedule_poke(self,message,send):self.poked.append((message,send))
            async def recover(self,key,*,owner=False):
                assert owner, 'only SUPERUSER command explicitly authorizes takeover'
                self.recovered.append(key);return 'resumed'
            def learn_message(self,message,plain):self.learned.append((message.message_id,plain))

        service = FakeService(); ai.service = service
        sent = []
        api_calls=[]

        class FakeBot(Bot):
            async def call_api(self, api, **data):
                api_calls.append((api,data))
                if api == 'get_login_info':return {'user_id':int(self.self_id),'nickname':'古户绘梨花'}
                if api == 'send_group_forward_msg':return {'message_id':991,'forward_id':'local-test'}
                if api == 'get_forward_msg':
                    return {'messages':[{'sender':{'nickname':'转发成员'},'message':[
                        {'type':'text','data':{'text':'转发测试内容'}},
                        {'type':'image','data':{'file':'a'*32+'.jpg'}}]}]}
                if api == 'get_msg':
                    return {'time': int(time.time()), 'message_type': 'group', 'message_id': 123,
                            'real_id': 123, 'sender': {'user_id': 8, 'nickname': '发图者'},
                            'message': [{'type': 'image', 'data': {'file': 'b' * 32 + '.jpg'}}]}
                sent.append(Message(data.get("message", "")))
                return {"message_id": 999}

        bot = FakeBot(Adapter(nonebot.get_driver()), "100")
        ana.model.GetReRule = lambda: "(群内梗)"
        ana.model.GetAna = lambda *args: "旧语录"
        idx = 0

        def event(text, directed=False, group=42, uid=7):
            nonlocal idx
            idx += 1
            return GroupMessageEvent.parse_obj(dict(time=int(time.time()), self_id=100, post_type="message",
                message_type="group", sub_type="normal", message_id=idx, group_id=group, user_id=uid,
                message=[{"type":"text","data":{"text":text}}], original_message=[{"type":"text","data":{"text":text}}],
                raw_message=text, font=0, sender={"user_id":uid,"nickname":"群友","role":"member"}, to_me=directed))

        def notice(user=7,target=100,group=42):
            return PokeNotifyEvent.parse_obj(dict(time=int(time.time()),self_id=100,post_type='notice',
                notice_type='notify',sub_type='poke',group_id=group,user_id=user,target_id=target))
        for e in [notice(target=8),notice(user=100),notice(group=99),notice(group=None)]:
            await handle_event(bot,e)
        assert not service.poked and not sent
        await handle_event(bot,notice())
        assert len(service.poked)==1 and not service.learned and not service.scheduled
        received,reply=service.poked.pop()
        assert received.user_id=='7' and received.notice=='poke' and received.message_id.startswith('poke-')
        await reply('戳我干嘛😏')
        assert api_calls[-1][0]=='send_group_msg' and api_calls[-1][1]['group_id']==42
        assert sent[-1].extract_plain_text()=='戳我干嘛😏'
        sent.clear()

        await handle_event(bot, event("普通聊天"))
        assert len(service.scheduled) == 1, "SuperAna's broad match must not claim a no-hit message"
        assert not sent
        service.scheduled.clear()
        await handle_event(bot, event("群内梗"))
        assert len(sent) == 1 and not service.scheduled, "advanced quote must suppress AI"
        assert service.learned[-1][1]=='群内梗', 'ordinary slang still reaches learner when a passive quote replies'
        sent.clear()
        await handle_event(bot, event("群内梗", directed=True))
        assert len(service.scheduled) == 1 and not sent, "AI @ takeover must suppress both passive handlers"
        _, send = service.scheduled.pop()
        await send("[CQ:at,qq=all]")
        assert len(sent[0]) == 1 and sent[0][0].type == "text", "model CQ must remain literal"
        sent.clear()
        learned_before=len(service.learned)
        await handle_event(bot, event("测试语录"))
        assert sent and not service.scheduled, "explicit quote command wins"
        assert len(service.learned)==learned_before, 'explicit commands must not enter learning window'
        sent.clear()
        before = len(service.observed)
        await handle_event(bot, event("你好", group=99))
        await handle_event(bot, event("你好", uid=100))
        assert len(service.observed) == before, "non-allowed groups and bot echoes excluded"
        ai.config.agent_chat_images_enabled = True
        class FakeMedia:
            async def prepare(self, history, call_api, **kwargs):
                return ai.PreparedMedia([], 'checked')
        ai.media_resolver = FakeMedia()
        picture = event('这是什么图', directed=True)
        picture.message.append(MessageSegment.image('a' * 32 + '.jpg'))
        await handle_event(bot, picture)
        assert service.scheduled[-1][0].media[0]['file'] == 'a' * 32 + '.jpg'
        assert service.prepare is not None, 'only unclaimed allowed events schedule media preparation'
        service.scheduled.clear()
        quoted = event('这个人是谁')
        quoted.message = Message([MessageSegment.reply(123), MessageSegment.at(100), MessageSegment.text('这个人是谁')])
        quoted.original_message = quoted.message.copy()
        await _check_reply(bot, quoted)
        _check_at_me(bot, quoted)
        assert not quoted.is_tome(), 'reproduce upstream removal of mention after quoting another sender'
        await handle_event(bot, quoted)
        assert service.scheduled[-1][0].directed, 'original structured bot mention must survive quote preprocessing'
        assert service.scheduled[-1][0].media[0]['file'] == 'b' * 32 + '.jpg'
        service.scheduled.clear()
        for mention in [MessageSegment.at(8), MessageSegment.at('all'), MessageSegment.text('[CQ:at,qq=100]')]:
            other = event('看图')
            other.original_message = Message([mention, MessageSegment.text('看图')])
            await handle_event(bot, other)
            assert not service.scheduled[-1][0].directed, 'other targets and literal CQ text are not a bot mention'
            service.scheduled.clear()
        forwarded=event('看看这段聊天记录',directed=True)
        forwarded.message.append(MessageSegment('forward',{'id':'observed-forward'}))
        await handle_event(bot,forwarded)
        observed,send=service.scheduled.pop()
        assert observed.forwards==('observed-forward',)
        _,notes=await service.prepare([observed.payload()],[observed.payload()],{"key":observed.key,"direct_ids":[observed.message_id],"seen":{}})
        assert '转发测试内容' in notes and any(a=='get_forward_msg' for a,_ in api_calls)
        # A later direct question has no new forward segment but must still resolve the earlier one.
        followup=event('读一下上面的聊天记录',directed=True)
        await handle_event(bot,followup)
        later,_=service.scheduled.pop()
        _,notes=await service.prepare([observed.payload(),later.payload()],[later.payload()],{"key":later.key,"direct_ids":[later.message_id],"seen":{}})
        assert '转发测试内容' in notes

        from src.plugins.agent_chat.presentation import parse
        import json
        await send(parse('QQ_REPLY '+json.dumps({'text':'哼😏','reply_to':str(observed.message_id),'faces':['捂脸']}),{str(observed.message_id)}))
        assert [s.type for s in sent[-1]]==['reply','text','face']
        assert api_calls[-1][0]=='send_msg' and api_calls[-1][1]['group_id']==42
        assert api_calls[-1][1]['message'][0].data['id']==str(observed.message_id)
        assert str(api_calls[-1][1]['message'][1].data['text'])=='哼😏'
        # Use the real Bot -> Adapter -> JSON serializer, replacing only the socket.
        adapter=Adapter(nonebot.get_driver());wire=[]
        class CaptureSocket:
            async def send(self,raw):
                frame=json.loads(raw);wire.append(frame)
                asyncio.get_running_loop().call_soon(adapter._result_store.add_result,
                    {'status':'ok','retcode':0,'data':({'user_id':101,'nickname':'古户绘梨花'} if frame['action']=='get_login_info' else {'message_id':999}),'echo':frame['echo']})
        adapter.connections['101']=CaptureSocket()
        native_bot=Bot(adapter,'101')
        for raw,expected in [
            ('QQ_REPLY '+json.dumps({'text':'好呀😏','reply_to':str(observed.message_id),'faces':['捂脸']}),['reply','text','face']),
            ('<QQ_REPLY>'+json.dumps({'text':'好呀🙂','reply_to':observed.message_id,'faces':['捂脸']})+'</QQ_REPLY>',['reply','text','face']),
            ('```json\nQQ_REPLY '+json.dumps({'text':'好呀🙂','reply_to':str(observed.message_id)})+'\n```',['reply','text']),
            ('<thinking>consider QQ_REPLY</thinking>正文🙂',['text']),
            ('QQ_REPLY '+json.dumps({'text':'保留正文','reply_to':[],'faces':[1]}),['text']),
            ('就这样😂',['text']),
            ('QQ_REPLY '+json.dumps({'text':'','reply_to':'','faces':['可爱']}),['face'])]:
            await native_bot.send(forwarded,ai.outgoing_message(parse(raw,{str(observed.message_id)})))
            assert [part['type'] for part in wire[-1]['params']['message']]==expected
            assert wire[-1]['params']['group_id']==42
        assert wire[0]['params']['message'][0]['data']['id']==str(observed.message_id)
        assert wire[0]['params']['message'][1]['data']['text']=='好呀😏'
        assert wire[0]['params']['message'][2]['data']['id']=='264'
        adapter.connections.clear()
        sent.clear()
        await handle_event(bot,event('ai 恢复',uid=7))
        assert service.recovered==[], 'ordinary group members cannot run recovery'
        service.scheduled.clear()
        await handle_event(bot,event('ai 恢复',uid=1))
        assert service.recovered==['100:group:42'] and not service.scheduled, 'SUPERUSER recovery wins over chat handlers'
        sent.clear()
        before=len(sent)
        await handle_event(bot,event('ai 清空记忆',uid=7))
        assert len(sent)==before, 'ordinary members cannot administer persistent memory'
        service.scheduled.clear()
        import sqlite3
        from src.plugins.agent_chat.knowledge import KnowledgeStore
        db=sqlite3.connect(':memory:');service.knowledge=KnowledgeStore(db)
        ids=[]
        for term in ('测试甲词','测试乙词'):
            item=service.knowledge.submit_slang('100:group:42',term,[{'key':'100:group:42','message_id':term,'text':term,'name':'群友','user_id':'7'}])
            ids.append(item['id'])
        with db:db.execute("UPDATE knowledge_slang SET meaning='测试解释'")
        command='ai 黑话确认 '+' '.join(str(i) for i in ids)
        await handle_event(bot,event(command,uid=7))
        assert db.execute("SELECT COUNT(*) FROM knowledge_slang WHERE status='confirmed'").fetchone()[0]==0
        await handle_event(bot,event(command,uid=1))
        assert db.execute("SELECT COUNT(*) FROM knowledge_slang WHERE status='confirmed'").fetchone()[0]==2
        assert '已确认 2 条' in str(sent[-1])
        await handle_event(bot,event(f'ai 黑话解锁 {ids[0]}',uid=7,group=99))
        assert service.knowledge.known_slang()[0]['locked']
        await handle_event(bot,event(f'ai 黑话解锁 {ids[0]}',uid=1,group=99))
        assert not next(r for r in service.knowledge.known_slang() if r['id']==ids[0])['locked']
        await handle_event(bot,event(f'ai 黑话历史 {ids[0]}',uid=1,group=99))
        assert '历史' in str(sent[-1])
        await handle_event(bot,event(f'ai 黑话回退 {ids[0]} 1',uid=1,group=99))
        assert next(r for r in service.knowledge.known_slang() if r['id']==ids[0])['locked']

        from src.plugins.agent_chat.memory import MemoryManager
        ai.config.agent_chat_memory_enabled=True
        ai.config.agent_chat_memory_background_enabled=True
        service.memory_manager=MemoryManager(service.knowledge,ai.config)
        await handle_event(bot,event('ai 后台记忆 全群 关',uid=7))
        assert service.memory_manager.settings('100:group:42')['background'], 'ordinary members cannot change memory controls'
        service.scheduled.clear()
        await handle_event(bot,event('ai 后台记忆 全群 关',uid=1))
        assert not service.memory_manager.settings('100:group:42')['background'] and not service.scheduled
        assert not service.memory_manager.settings('100:group:43')['background']
        await handle_event(bot,event('ai 后台记忆 开',uid=1))
        assert service.memory_manager.settings('100:group:42')['background']
        await handle_event(bot,event('ai 记忆状态',uid=1))
        assert '待整理' in str(sent[-1])
        service.knowledge.append_memory('100:group:42','activeTopic','准备一起玩游戏')
        service.knowledge.append_memory('100:group:42','memberImpression','喜欢FPS',{'target':'7'},{'7':'群友甲'})
        service.knowledge.append_memory('100:group:43','activeTopic','另群记忆不可泄露')
        memory_count=db.execute('SELECT COUNT(*) FROM knowledge_memory').fetchone()[0]
        before_api=len(api_calls)
        await handle_event(bot,event('ai 记忆',uid=7))
        assert len(api_calls)==before_api, 'ordinary members cannot export memory'
        await handle_event(bot,event('ai 记忆',uid=1))
        action,card=api_calls[-1]
        assert action=='send_group_forward_msg' and card['group_id']==42
        assert card['source']=='当前对话记忆' and len(card['news'])==2
        body='\n'.join(str(node.data['content']) for node in card['messages'])
        assert '群友甲：喜欢FPS' in body and '准备一起玩游戏' in body
        assert 'activeTopic' not in body and 'memberImpression' not in body and '删除编号' not in body
        assert '另群记忆不可泄露' not in body and '准备一起玩游戏' not in str(card['news'])
        for node in card['messages']:
            assert len(node.data['content'])==1 and node.data['content'][0].type=='text'
        await handle_event(bot,event('ai 记忆 管理',uid=1))
        assert '删除编号' in str(api_calls[-1][1]['messages'])
        before_api=len(api_calls)
        await handle_event(bot,event('ai 记忆',uid=1,group=99))
        assert not any(api=='send_group_forward_msg' for api,_ in api_calls[before_api:])
        ai.config.agent_chat_private_users=frozenset({1})
        service.knowledge.append_memory('100:private:1','activeTopic','私聊记忆')
        private_event=PrivateMessageEvent.parse_obj(dict(time=int(time.time()),self_id=100,post_type='message',
            message_type='private',sub_type='friend',message_id=9999,user_id=1,
            message=[{'type':'text','data':{'text':'ai 记忆'}}],raw_message='ai 记忆',font=0,sender={'user_id':1,'nickname':'主人'}))
        await handle_event(bot,private_event)
        assert api_calls[-1][0]=='send_private_forward_msg' and api_calls[-1][1]['user_id']==1
        assert '私聊记忆' in str(api_calls[-1][1]['messages']) and '群友甲' not in str(api_calls[-1][1]['messages'])
        ai.config.agent_chat_private_users=frozenset()
        assert db.execute('SELECT COUNT(*) FROM knowledge_memory').fetchone()[0]==memory_count+1
        ai.config.agent_chat_slang_enabled=False
        before=len(service.learned)
        await handle_event(bot,event('普通的新聊天'))
        assert len(service.learned)==before+1, 'memory-only mode still receives unmentioned text'
        # Remote moderation in a non-AI group must not activate chat or collect its history.
        from src.plugins.agent_chat.slang_report import send_report,build_report
        remote_id=service.knowledge.submit_slang('100:group:43','另群测试词',[
            dict(key='100:group:43',message_id=str(i),text='秘密原文 另群测试词',name='私有昵称',user_id='771122') for i in range(2)])['id']
        with db:db.execute("UPDATE knowledge_slang SET meaning='字面[CQ:at,qq=all] 解释' WHERE id=?",(remote_id,))
        outsider_id=service.knowledge.submit_slang('101:group:43','其他账号私词',[
            dict(key='101:group:43',message_id='900',text='其他账号私词',name='成员',user_id='8')])['id']
        before_api=len(api_calls);before_observed=len(service.observed);before_learned=len(service.learned)
        await handle_event(bot,event('ai 黑话 全部',uid=7,group=99))
        assert len(api_calls)==before_api, 'ordinary members cannot export reports'
        await handle_event(bot,event('ai 黑话 全部',uid=1,group=99))
        api,data=api_calls[-1]
        assert api=='send_group_forward_msg' and data['group_id']==99
        assert data['source']=='黑话审核汇总' and len(data['news'])==2
        assert '字面[CQ:' not in str(data['news'])
        assert len(data['messages'])>=3, 'one forwarded container has header and separate source-group nodes'
        exported='\n'.join(str(node.data['content']) for node in data['messages'])
        assert '来源群 42' in exported and '来源群 43' in exported
        assert '秘密原文' not in exported and '私有昵称' not in exported and '其他账号私词' not in exported
        assert all(node.type=='node' and node.data['user_id']=='100' and node.data['nickname']=='古户绘梨花' and
                   len(node.data['content'])==1 and node.data['content'][0].type=='text' for node in data['messages'])
        await handle_event(bot,event(f'ai 黑话确认 {remote_id}',uid=7,group=99))
        assert db.execute('SELECT status FROM knowledge_slang WHERE id=?',(remote_id,)).fetchone()[0]=='candidate'
        await handle_event(bot,event(f'ai 黑话确认 {remote_id}',uid=1,group=99))
        assert db.execute('SELECT status FROM knowledge_slang WHERE id=?',(remote_id,)).fetchone()[0]=='confirmed'
        await handle_event(bot,event(f'ai 黑话确认 {outsider_id}',uid=1,group=99))
        assert db.execute('SELECT status FROM knowledge_slang WHERE id=?',(outsider_id,)).fetchone()[0]=='candidate'
        before_recover=len(service.recovered)
        await handle_event(bot,event('ai 恢复',uid=1,group=99))
        await handle_event(bot,event('ai 后台记忆 全群 开',uid=1,group=99))
        await handle_event(bot,event('普通聊天',directed=True,uid=1,group=99))
        assert len(service.recovered)==before_recover and len(service.observed)==before_observed and len(service.learned)==before_learned
        assert ai.config.agent_chat_groups==frozenset({42})
        # Check exact OneBot wire JSON for native custom forward nodes.
        adapter.connections['101']=CaptureSocket();wire.clear()
        await send_report(native_bot,event('ai 黑话',uid=1,group=99),build_report(service.knowledge,'100','全部'))
        assert wire[-1]['action']=='send_group_forward_msg' and wire[-1]['params']['group_id']==99
        assert all(node['type']=='node' and node['data']['user_id']=='101' and node['data']['nickname']=='古户绘梨花' and
            node['data']['content'][0]['type']=='text' for node in wire[-1]['params']['messages'])
        # A realistic long report must stay complete while its outer QQ card stays small.
        from src.plugins.agent_chat.slang_report import SlangReport
        long_report=SlangReport(tuple(f'节点{i}\n'+('完整内容🙂 '*400)[:1750] for i in range(10)),1,7,600)
        wire.clear()
        await send_report(native_bot,event('ai黑话',uid=1,group=99),long_report)
        sent_report=wire[-1]['params']
        assert len(sent_report['messages'])==10
        assert tuple(n['data']['content'][0]['data']['text'] for n in sent_report['messages'])==long_report.nodes
        assert len(json.dumps({k:sent_report[k] for k in ('source','news','summary','prompt')},ensure_ascii=False).encode())<512
        assert len([f for f in wire if f['action']=='send_group_forward_msg'])==1
        adapter.connections.clear()
        # Exercise optional actions through a real NoneBot Bot/Adapter connection.
        from dataclasses import replace
        from src.plugins.agent_chat.presentation import social_targets
        native_record=replace(observed,key='101:group:42')
        service.store.append(native_record)
        scope=social_targets([native_record.payload()],native_record.key,ai.config)
        plan=parse('QQ_REPLY '+json.dumps({'text':'接住啦🙂','reply_to':'','faces':[],
            'mentions':['7'],'reaction':{'message_id':str(observed.message_id),'emoji':'👍'},'poke':'7'}),set(),True,scope)
        adapter.connections['101']=CaptureSocket();wire.clear()
        async def normal_send(value):
            return await native_bot.send_group_msg(group_id=42,message=ai.outgoing_message(value))
        assert await service.social.send(native_bot,native_record.key,plan,normal_send)
        assert plan.sent_message_id=='999', 'native receipt must reach observation anchors'
        assert [f['action'] for f in wire]==['send_group_msg','set_msg_emoji_like','group_poke']
        assert wire[0]['params']['message'][0]=={'type':'at','data':{'qq':'7'}}
        assert wire[1]['params']=={'message_id':int(observed.message_id),'emoji_id':'128077','set':True,'_timeout':5}
        assert wire[2]['params']=={'group_id':42,'user_id':7,'_timeout':5}
        adapter.connections.clear()
        # A gateway failure returns one short notice, never a multi-message plain-text flood or retry.
        original_call=bot.call_api;failed=[]
        async def reject_forward(api,**data):
            if api=='send_group_forward_msg':failed.append(api);raise RuntimeError('simulated gateway failure')
            return await original_call(api,**data)
        bot.call_api=reject_forward
        before=len(sent)
        await handle_event(bot,event('ai 黑话 全部',uid=1,group=99))
        assert len(failed)==1 and len(sent)==before+1 and '合并转发未确认' in str(sent[-1])
        before=len(sent)
        await handle_event(bot,event('ai 记忆',uid=1))
        assert len(failed)==2 and len(sent)==before+1 and 'ai 记忆' in str(sent[-1])
        bot.call_api=original_call
        assert service.knowledge.learning_count()==0
        service.knowledge=None;db.close();service.store.db.close()
        ai.config.agent_chat_images_enabled = False
        ai.media_resolver = None
        ai.service = None
        await handle_event(bot, event("你好", directed=True))
        assert sent, "disabled AI retains old @ reply"
        print("PASS: readable memory forward/group-private scope/owner gate/failure no-flood, native PokeNotifyEvent routing and literal response, real NoneBot dispatch, SuperAna arbitration, mention recovery, literal CQ, image/forward routing, reply+face segments, SUPERUSER recovery, remote slang review, grouped forward wire, native mention/reaction/poke APIs, failure no-flood, allowlist, disabled fallback")
        os.chdir(ROOT)


if __name__ == "__main__": asyncio.run(main())
