"""Large forward bodies must not become unbounded QQ card previews."""
import importlib,json,unittest
from types import SimpleNamespace
from test_agent_chat import PACKAGE
from nonebot.adapters.onebot.v11 import GroupMessageEvent
reports=importlib.import_module(PACKAGE+'.slang_report')

class SlangPreviewTests(unittest.IsolatedAsyncioTestCase):
 async def run_report(self,event,fail=False):
  calls=[]
  class Bot:
   async def call_api(self,action,**params):
    calls.append((action,params))
    if action=='get_login_info':return {'user_id':100,'nickname':'实际昵称🙂'}
    if fail:raise RuntimeError('send failed')
    return {'message_id':999}
  bodies=tuple(f'节点{i} '+('完整中文🙂 [CQ:at,qq=all] '*100)[:1700] for i in range(10))
  report=reports.SlangReport(bodies,2,7,600)
  if fail:
   with self.assertRaises(RuntimeError):await reports.send_report(Bot(),event,report)
  else:self.assertEqual(await reports.send_report(Bot(),event,report),{'message_id':999})
  self.assertEqual(len(calls),2,'one identity request and one send; no retry')
  action,params=calls[-1]
  self.assertEqual(tuple(n.data['content'][0].data['text'] for n in params['messages']),bodies)
  for node in params['messages']:
   self.assertEqual(node.data['user_id'],'100');self.assertEqual(node.data['nickname'],'实际昵称🙂')
   self.assertEqual([s.type for s in node.data['content']],['text'])
  preview=json.dumps({k:params[k] for k in ('source','news','summary','prompt')},ensure_ascii=False)
  self.assertLess(len(preview.encode()),512)
  self.assertNotIn('完整中文',preview);self.assertNotIn('[CQ:',preview);self.assertIn('2/7',preview)
  self.assertIn('600',preview)
  return action,params
 def group_event(self):
  return GroupMessageEvent.parse_obj(dict(time=0,self_id=100,post_type='message',message_type='group',sub_type='normal',message_id=1,group_id=99,user_id=1,message=[{'type':'text','data':{'text':'ai黑话'}}],raw_message='ai黑话',font=0,sender={'user_id':1,'nickname':'管理员'}))
 async def test_full_group_report_has_small_preview_and_literal_nodes(self):
  action,params=await self.run_report(self.group_event())
  self.assertEqual(action,'send_group_forward_msg');self.assertEqual(params['group_id'],99)
  self.assertNotIn('user_id',params)
 async def test_private_report_has_same_bounded_preview(self):
  action,params=await self.run_report(SimpleNamespace(user_id=1))
  self.assertEqual(action,'send_private_forward_msg');self.assertEqual(params['user_id'],1)
  self.assertNotIn('group_id',params)
 async def test_failed_long_report_is_not_retried(self):
  await self.run_report(self.group_event(),fail=True)

if __name__=='__main__':unittest.main()
