import asyncio,importlib,json,time,unittest
from dataclasses import replace
from unittest.mock import patch
import test_agent_chat as base
from test_agent_chat import PACKAGE,message,cfg
F=importlib.import_module(PACKAGE+'.forwards')

class ForwardFixTests(unittest.IsolatedAsyncioTestCase):
 async def test_live_qq_future_clock_skew_does_not_hide_forward(self):
  now=time.time();calls=[]
  async def api(action,**params):
   calls.append(params);return {'messages':[{'sender':{'nickname':'测试'},'message':[{'type':'text','data':{'text':'实际节点正文'}}]}]}
  records=[replace(message(),forwards=('root',),timestamp=now+2.4).payload()]
  _,notes=await F.ForwardResolver(cfg()).prepare(records,api)
  self.assertIn('实际节点正文',notes);self.assertEqual(len(calls),1)
  for stamp in (now+125,now-605):
   calls.clear();await F.ForwardResolver(cfg()).prepare([{**records[0],'timestamp':stamp}],api);self.assertFalse(calls)
 async def test_followup_can_find_earlier_forward_without_reloading_unrelated_material(self):
  old=replace(message(mid='1',directed=False),forwards=('old',)).payload()
  follow=replace(message(mid='2'),text='你看看上面这个记录讲了啥').payload()
  self.assertEqual(F.forward_context([old,follow],[follow]),[old])
  ordinary={**follow,'text':'今天吃什么'}
  self.assertEqual(F.forward_context([old,ordinary],[ordinary]),[])
  ambient={**follow,'directed':False}
  self.assertEqual(F.forward_context([old,ambient],[ambient]),[])
  current={**follow,'forwards':('new',)}
  self.assertEqual(F.forward_context([old,current],[current]),[current])
 async def test_fetch_uses_adapter_timeout_and_reports_only_safe_diagnostics(self):
  async def api(action,**kwargs):
   self.assertEqual(kwargs['_timeout'],15)
   raise ValueError('private payload and credential')
  with self.assertLogs('agent_chat',level='WARNING') as captured:
   _,notes=await F.ForwardResolver(cfg()).prepare([replace(message(),forwards=('root',)).payload()],api)
  self.assertIn('ValueError',str(captured.output));self.assertNotIn('credential',str(captured.output));self.assertIn('获取失败',notes)
 async def test_cancel_during_reading_is_not_swallowed(self):
  async def api(*args,**kw):raise asyncio.CancelledError()
  with self.assertRaises(asyncio.CancelledError):await F.ForwardResolver(cfg()).prepare([replace(message(),forwards=('root',)).payload()],api)

class ForwardHistoryTests(unittest.IsolatedAsyncioTestCase):
 asyncSetUp=base.ServiceTests.asyncSetUp
 asyncTearDown=base.ServiceTests.asyncTearDown
 send=base.ServiceTests.send
 async def test_reference_outside_twenty_text_messages_reaches_model_without_bulk_chat_replay(self):
  first=replace(message(mid='1',directed=False),text='[forward]',forwards=('earlier-forward',),timestamp=time.time()-10)
  self.service.observe(first)
  for i in range(2,40):self.service.observe(replace(message(mid=str(i),directed=False),text='无关背景'+str(i)))
  latest=replace(message(mid='40'),text='总结一下上面的聊天记录')
  async def prepare(history,pending):
   self.assertIn('earlier-forward',[ref for m in history for ref in m.get('forwards',[])])
   self.assertLessEqual(len(pending),20)
   async def api(action,**params):return {'messages':[{'sender':{'nickname':'转发者'},'message':[{'type':'text','data':{'text':'转发里的重要结论'}}]}]}
   return await F.ForwardResolver(cfg()).prepare(F.forward_context(history,pending),api)
  self.service.observe(latest);self.service.schedule(latest,self.send,prepare)
  await self.service.tasks[latest.key]
  self.assertIn('转发里的重要结论',self.client.prompts[-1][1]);self.assertNotIn('无关背景2"',self.client.prompts[-1][1])
  self.assertEqual(self.sent,['你好呀'])

if __name__=='__main__':unittest.main()
