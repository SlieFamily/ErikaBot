import asyncio,importlib,json,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_agent_chat as base
from test_agent_chat import PACKAGE,cfg,message
P=importlib.import_module(PACKAGE+'.presentation')
I=importlib.import_module(PACKAGE+'.interactions')
KEY='100:group:42'

def envelope(**extra):
 return 'QQ_REPLY '+json.dumps(dict(text='好呀🙂',reply_to='',faces=[],**extra),ensure_ascii=False)

class SocialTargetTests(unittest.TestCase):
 def test_recent_observed_members_only_not_quoted_ids_other_groups_or_bot(self):
  now=time.time()
  records=[message().payload(),replace(message(mid='2'),user_id='8',timestamp=now+2).payload(),
   replace(message(mid='3'),user_id='9',timestamp=now-601).payload(),message(key='100:group:43',mid='4').payload(),
   replace(message(mid='5'),user_id='100').payload(),replace(message(mid='6'),user_id='all').payload(),
   replace(message(mid='7'),user_id='11',timestamp=now+121).payload()]
  records[0]['reply_user_id']='12345';records[0]['reply_to']='888'
  scope=P.social_targets(records,KEY,cfg(),now=now)
  self.assertEqual(scope,{'mentions':{'7','8'},'poke':{'7','8'},'reaction':{'1','2'}})
  for key,proactive in [('100:private:7',False),(KEY,True)]:
   self.assertFalse(any(P.social_targets(records,key,cfg(),proactive).values()))
 def test_actions_disabled_independently_and_legacy_output_still_works(self):
  scope=P.social_targets([message().payload()],KEY,cfg(agent_chat_mentions_enabled=False,agent_chat_poke_enabled=False))
  self.assertEqual(scope,{'mentions':set(),'poke':set(),'reaction':{'1'}})
  p=P.parse(envelope(),set());self.assertEqual(p,'好呀🙂');self.assertFalse(p.reaction)
 def test_invalid_target_stripped_and_no_all_mentions(self):
  scope=P.social_targets([message().payload()],KEY,cfg())
  p=P.parse(envelope(mentions=['all','999'],reaction={'message_id':'999','emoji':'👍'},poke='999'),set(),social=scope)
  self.assertEqual(p,'好呀🙂');self.assertFalse(p.mentions or p.reaction or p.poke)
 def test_unknown_fields_and_malformed_action_shapes_fail_closed(self):
  scope=P.social_targets([message().payload()],KEY,cfg())
  for ext in [{'mentions':['7']*3},{'mentions':[7]},{'poke':7},{'reaction':[]},
              {'reaction':{'message_id':'1','emoji':'👍','api':'delete_msg'}},{'api':'group_poke'}]:
   self.assertFalse(P.parse(envelope(**ext),set(),social=scope))
 def test_silent_cancels_all_and_optional_only_actions_remain_truthy(self):
  scope=P.social_targets([message().payload()],KEY,cfg())
  data=dict(text='[SILENT]',reply_to='',faces=[],mentions=['7'],reaction={'message_id':'1','emoji':'👍'},poke='7')
  p=P.parse('QQ_REPLY '+json.dumps(data),set(),social=scope)
  self.assertEqual(p,'[SILENT]');self.assertFalse(p.reaction or p.mentions or p.poke)
  data.update(text='',mentions=[],poke='');p=P.parse('QQ_REPLY '+json.dumps(data),set(),social=scope)
  self.assertTrue(p);self.assertEqual(P.segments(p),[]);self.assertEqual(p.reaction,('1','128077'))
 def test_literal_cq_does_not_gain_actions_and_native_at_uses_factory(self):
  p=P.parse('[CQ:at,qq=all][CQ:poke,qq=7]',set())
  self.assertEqual([s.type for s in I.qq_message(p)],['text'])
  p=P.parse(envelope(mentions=['7','7']),set(),social={'mentions':{'7'},'reaction':set(),'poke':set()})
  self.assertEqual(p.mentions,('7',));self.assertEqual(I.qq_message(p)[0].data,{'qq':'7'})

class InteractionSenderTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  self.store=base.Store(self.path);self.store.append(message());self.config=cfg()
  self.actions=I.SocialActions(self.config,self.store);self.calls=[];self.sent=[];self.error=False
  parent=self
  class Bot:
   self_id='100'
   async def set_msg_emoji_like(self,**args):
    parent.calls.append(('reaction',args))
    if parent.error:raise RuntimeError('secret error body')
    return {'result':True}
   async def group_poke(self,**args):
    parent.calls.append(('poke',args));return None
  self.bot=Bot()
 async def asyncTearDown(self):self.store.db.close();self.tmp.cleanup()
 async def send(self,p):self.sent.append(p)
 def plan(self,text='hi',reaction=('1','128077'),poke='7',mentions=('7',)):
  return P.Outgoing(text,mentions=mentions,reaction=reaction,poke=poke)
 async def test_text_then_optional_actions_and_failure_does_not_suppress_text(self):
  self.error=True
  with self.assertLogs('agent_chat',level='WARNING') as logs:
   self.assertTrue(await self.actions.send(self.bot,KEY,self.plan(),self.send))
  self.assertEqual(str(self.sent[0]),'hi');self.assertEqual([a for a,_ in self.calls],['reaction','poke'])
  self.assertNotIn('secret',str(logs.output))
 async def test_no_empty_message_send_for_reaction_only(self):
  self.assertTrue(await self.actions.send(self.bot,KEY,self.plan(text='',poke='',mentions=()),self.send))
  self.assertFalse(self.sent);self.assertEqual(len(self.calls),1)
 async def test_native_nonzero_result_is_a_failure_and_zero_is_success(self):
  async def rejected(**kwargs):return {'result':1,'errMsg':'private server text'}
  self.bot.set_msg_emoji_like=rejected
  with self.assertLogs('agent_chat',level='WARNING') as logs:
   self.assertFalse(await self.actions.send(self.bot,KEY,self.plan(text='',poke='',mentions=()),self.send))
  self.assertNotIn('private',str(logs.output))
  async def accepted():return {'result':0,'errMsg':''}
  self.assertTrue(await self.actions._attempt('100:group:43','reaction','2',30,accepted))
 async def test_feature_switches_revalidated_and_reset_preserves_budget(self):
  self.config.agent_chat_poke_enabled=False;self.config.agent_chat_mentions_enabled=False
  await self.actions.send(self.bot,KEY,self.plan(),self.send)
  self.assertEqual([a for a,_ in self.calls],['reaction']);self.assertFalse(self.sent[0].mentions)
  self.store.reset(KEY)
  self.assertFalse(self.store.reserve_interaction(KEY,'reaction','1',30))
 async def test_text_failure_never_proceeds_to_optional_actions(self):
  async def fail(p):raise RuntimeError('failed normal message')
  with self.assertRaises(RuntimeError):await self.actions.send(self.bot,KEY,self.plan(),fail)
  self.assertFalse(self.calls)
 async def test_expired_or_other_group_targets_are_rejected_at_send(self):
  with patch.object(I,'social_targets',wraps=I.social_targets):
   old=replace(message(),timestamp=time.time()-601)
   with self.store.db:self.store.db.execute('UPDATE messages SET payload=?',(json.dumps(old.payload()),))
   self.assertTrue(await self.actions.send(self.bot,KEY,self.plan(),self.send))
  self.assertFalse(self.calls);self.assertFalse(self.sent[-1].mentions)
  self.assertTrue(await self.actions.send(self.bot,'100:group:99',self.plan(),self.send));self.assertFalse(self.calls)
 async def test_cooldown_and_duplicate_survive_reopen_and_failures(self):
  self.error=True
  with self.assertLogs('agent_chat',level='WARNING'):await self.actions.send(self.bot,KEY,self.plan(),self.send)
  count=len(self.calls);self.store.db.close();self.store=base.Store(self.path);self.actions=I.SocialActions(self.config,self.store)
  await self.actions.send(self.bot,KEY,self.plan(),self.send);self.assertEqual(len(self.calls),count)
  # A reaction stays deduplicated even after its short group cooldown.
  self.assertFalse(self.store.reserve_interaction(KEY,'reaction','1',30,now=time.time()+31))
  self.assertTrue(self.store.reserve_interaction(KEY,'reaction','2',30,now=time.time()+31))
 async def test_poke_cooldown_is_per_group_and_does_not_block_other_groups(self):
  self.assertTrue(self.store.reserve_interaction(KEY,'poke','7',300,now=1000))
  self.assertFalse(self.store.reserve_interaction(KEY,'poke','8',300,now=1100))
  self.assertTrue(self.store.reserve_interaction('100:group:43','poke','7',300,now=1100))
  self.assertTrue(self.store.reserve_interaction(KEY,'poke','7',300,now=1301))
 async def test_cancellation_is_not_swallowed_and_claim_is_retained(self):
  async def cancel(**kwargs):raise asyncio.CancelledError()
  self.bot.group_poke=cancel
  with self.assertRaises(asyncio.CancelledError):await self.actions.send(self.bot,KEY,self.plan(text='',reaction=(),mentions=()),self.send)
  self.assertFalse(self.store.reserve_interaction(KEY,'poke','7',300))

class InteractionServiceTests(unittest.IsolatedAsyncioTestCase):
 asyncSetUp=base.ServiceTests.asyncSetUp
 asyncTearDown=base.ServiceTests.asyncTearDown
 submit=base.ServiceTests.submit
 send=base.ServiceTests.send
 async def test_model_selected_actions_survive_final_filter_without_extra_call(self):
  self.client.answer=envelope(mentions=['7'],reaction={'message_id':'1','emoji':'👍'},poke='7')
  await self.submit(message())
  self.assertEqual(self.sent[0].mentions,('7',));self.assertEqual(self.sent[0].reaction,('1','128077'));self.assertEqual(self.sent[0].poke,'7')
  self.assertEqual(len(self.client.prompts),1);self.assertIn('"mentions":["7"]',self.client.prompts[0][1])
 async def test_reaction_only_is_not_replaced_with_empty_answer_warning(self):
  self.client.answer='QQ_REPLY '+json.dumps(dict(text='',reply_to='',faces=[],reaction={'message_id':'1','emoji':'👍'}))
  await self.submit(message());self.assertEqual(str(self.sent[0]),'');self.assertEqual(self.sent[0].reaction,('1','128077'))
 async def test_filtered_control_body_cannot_escape_via_social_actions(self):
  self.client.answer=envelope(mentions=['7'],reaction={'message_id':'1','emoji':'👍'},poke='7').replace('好呀🙂','QQ_BRIDGE_SEARCH_POLICY private')
  await self.submit(message());self.assertNotIn('private',str(self.sent[0]));self.assertFalse(getattr(self.sent[0],'poke',''))
 async def test_failed_optional_only_send_does_not_suspend_session_or_mark_activity(self):
  self.client.answer='QQ_REPLY '+json.dumps(dict(text='',reply_to='',faces=[],reaction={'message_id':'1','emoji':'👍'}))
  async def skipped(p):return False
  m=message();self.service.observe(m);self.service.schedule(m,skipped)
  await asyncio.gather(*list(self.service.tasks.values()))
  self.assertFalse(self.store.session(KEY)[2]);self.assertEqual(self.store.activity(KEY)[2],0)
  self.assertEqual(self.store.db.execute('SELECT status FROM dispatches').fetchone()[0],'silent')

if __name__=='__main__':unittest.main()
