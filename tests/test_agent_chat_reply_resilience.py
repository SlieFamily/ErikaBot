import asyncio,importlib,json,time,unittest
from dataclasses import replace
import test_agent_chat as base
from test_agent_chat import PACKAGE,message
P=importlib.import_module(PACKAGE+'.presentation')
I=importlib.import_module(PACKAGE+'.interactions')

class EnvelopeTests(unittest.TestCase):
 def test_whole_xml_fence_whitespace_colon_wrappers_preserve_native_actions(self):
  body=json.dumps(dict(text='好呀🙂',reply_to='1',faces=['捂脸']),ensure_ascii=False)
  forms=['QQ_REPLY '+body,'QQ_REPLY\n'+body,'QQ_REPLY:'+body,'QQ_REPLY： '+body,
         'QQ_REPLY'+body,'<QQ_REPLY>'+body+'</QQ_REPLY>','```json\nQQ_REPLY '+body+'\n```',
         '```\n<QQ_REPLY>'+body+'</QQ_REPLY>\n```','<QQ_REPLY>```json\n'+body+'\n```</QQ_REPLY>']
  for raw in forms:
   with self.subTest(raw=raw):
    result=P.parse(raw,{'1'})
    self.assertEqual(result,'好呀🙂');self.assertEqual(result.reply_to,'1');self.assertEqual(result.faces,(264,))
    self.assertEqual([s.type for s in I.qq_message(result)],['reply','text','face'])
 def test_protocol_in_reasoning_never_blocks_plain_final_answer(self):
  for opening,closing in [('<thinking>','</thinking>'),('<analysis>','</analysis>'),('&lt;think&gt;','&lt;/think&gt;')]:
   result=P.parse(opening+'consider QQ_REPLY here'+closing+'正常回答🙂',set())
   self.assertEqual(result,'正常回答🙂')
  self.assertFalse(P.parse('QQ_REPLY {"text":"secret</thinking>tail","reply_to":"1"}',{'1'}))
  self.assertFalse(P.parse('<thinking>QQ_REPLY never finished',set()))
 def test_optional_defaults_numeric_reply_and_same_chat_allowlist(self):
  raw='QQ_REPLY '+json.dumps(dict(text='正文',reply_to=1))
  self.assertEqual(P.parse(raw,{'1'}).reply_to,'1')
  self.assertFalse(P.parse(raw,{'2'}).reply_to)
  for bad in [True,1.1,2**64,[],{'id':'1'}]:
   r=P.parse('QQ_REPLY '+json.dumps(dict(text='正文',reply_to=bad)),{'1'})
   self.assertEqual(r,'正文');self.assertFalse(r.reply_to)
 def test_ambiguous_truncated_duplicate_or_prose_envelopes_cannot_leak_or_execute(self):
  body='{"text":"ok","reply_to":"1"}'
  for raw in ['QQ_REPLY '+body+' extra','intro <QQ_REPLY>'+body+'</QQ_REPLY>',
              '<QQ_REPLY>'+body,'QQ_REPLY {"text":"ok",','QQ_REPLY '+body+body,
              'QQ_REPLY {"text":"one","text":"two"}',
              'QQ_REPLY {"text":"ok","poke":"7","poke":"8"}',
              'QQ_REPLY __import__("os").system("anything")',
              'I am discussing QQ_REPLY','{"text":"ok","note":"QQ_REPLY","reply_to":"1"}']:
   self.assertFalse(P.parse(raw,{'1'}),raw)
 def test_silent_and_literal_cq_remain_safe_after_tolerant_decode(self):
  r=P.parse('<QQ_REPLY>{"text":"[SILENT]","reply_to":1,"faces":["捂脸"]}</QQ_REPLY>',{'1'})
  self.assertEqual(r,'[SILENT]');self.assertFalse(r.reply_to or r.faces)
  r=P.parse('<QQ_REPLY>{"text":"[CQ:at,qq=all]","reply_to":999}</QQ_REPLY>',{'1'})
  self.assertEqual([s.type for s in I.qq_message(r)],['text'])
  self.assertEqual(I.qq_message(r)[0].data['text'],'[CQ:at,qq=all]')

class ServiceTests(unittest.IsolatedAsyncioTestCase):
 asyncSetUp=base.ServiceTests.asyncSetUp
 asyncTearDown=base.ServiceTests.asyncTearDown
 submit=base.ServiceTests.submit
 send=base.ServiceTests.send
 async def test_xml_answer_reaches_delivery_once_without_extra_model_turn(self):
  self.client.answer='<QQ_REPLY>{"text":"回复🙂","reply_to":1}</QQ_REPLY>'
  await self.submit(message())
  self.assertEqual(len(self.sent),1);self.assertEqual(self.sent[0],'回复🙂');self.assertEqual(self.sent[0].reply_to,'1')
  self.assertFalse(self.store.session(message().key)[2]);self.assertEqual(len(self.client.prompts),1)
 async def test_reasoning_marker_does_not_turn_valid_answer_into_error_notice(self):
  self.client.answer='<thinking>use QQ_REPLY? no</thinking>正常正文'
  await self.submit(message());self.assertEqual(self.sent,['正常正文'])
 async def test_stale_quote_is_removed_before_send_but_body_is_kept(self):
  m=replace(message(),timestamp=time.time()-601);self.store.append(m)
  from types import SimpleNamespace
  calls=[]
  async def send(v):calls.append(v);return {'message_id':42}
  plan=P.Outgoing('正文','1')
  self.assertTrue(await self.service.social.send(SimpleNamespace(self_id='100'),m.key,plan,send))
  self.assertEqual(str(calls[0]),'正文');self.assertFalse(calls[0].reply_to)
  self.assertEqual(plan.sent_message_id,'42')
 async def test_network_send_failure_is_never_retried_and_remains_uncertain(self):
  self.client.answer='<QQ_REPLY>{"text":"回复","reply_to":1}</QQ_REPLY>'
  attempts=[]
  async def fail(v):attempts.append(v);raise TimeoutError()
  m=message();self.service.observe(m);self.service.schedule(m,fail)
  await asyncio.gather(*list(self.service.tasks.values()))
  self.assertEqual(len(attempts),1)
  self.assertEqual(self.store.db.execute('SELECT status FROM dispatches').fetchone()[0],'delivery_uncertain')

if __name__=='__main__':unittest.main()
