"""No QQ/model calls: image relevance, receipt durability, cache bounds and private notes."""
import asyncio,base64,importlib,json,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import test_agent_chat as core
from test_agent_chat_media import png
m=importlib.import_module(core.PACKAGE+'.media')
p=importlib.import_module(core.PACKAGE+'.presentation')

def image(mid='1',key='100:group:42',text='[图片]',file='abcdef.png',directed=False):
 return replace(core.message(mid=mid,key=key,directed=directed),text=text,media=({'file':file},)).payload()
def scope(ids=(),seen=None):return dict(key='100:group:42',session_id='s',direct_ids=list(ids),seen=seen or {})

class SelectionTests(unittest.TestCase):
 def test_plain_text_does_not_attach_old_or_background_images(self):
  old=image();new=core.message(mid='2').payload()
  self.assertEqual(m.select_images([old,new],[new],scope(['2'])),[])
  self.assertEqual(m.select_images([old,new],[old,new],scope(['2'])),[])
 def test_current_quoted_and_explicit_followup_select_relevant_images(self):
  a=image();b=image('2',file='second.png');q=replace(core.message(mid='3'),text='再看看图里的字',reply_to='1').payload()
  self.assertEqual([r[0]['message_id'] for r in m.select_images([a,b,q],[q],scope(['3']))],['1'])
  q['text']='这是什么';self.assertEqual([r[0]['message_id'] for r in m.select_images([a,b,q],[q],scope(['3']))],['1'])
  q['text']='再看看图里的字';q['reply_to']='';self.assertEqual([r[0]['message_id'] for r in m.select_images([a,b,q],[q],scope(['3']))],['2'])
  self.assertEqual(m.select_images([a],[a],scope(['1'])),[(a,True)])
 def test_merged_questions_keep_both_current_and_quoted_image_candidates(self):
  a=image('1');b=image('2',file='another.png',directed=True)
  q=replace(core.message(mid='3'),text='这个呢',reply_to='1').payload()
  result=m.select_images([a,b,q],[b,q],scope(['2','3']))
  self.assertEqual({r[0]['message_id'] for r in result},{'1','2'})
 def test_ambient_uses_only_new_same_chat_nonstale_images(self):
  a=image();b=image('2');foreign=image('3',key='100:group:99');old=image('4');old['timestamp']-=601
  selected=m.select_images([a,b,foreign,old],[b,foreign,old],scope())
  self.assertEqual(selected,[(b,False)])
 def test_future_batch_is_not_an_answer_target(self):
  later=image('2',directed=True);current=core.message(mid='1').payload()
  self.assertEqual(m.select_images([current,later],[current,later],scope(['1'])),[])

class CacheTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.resolver=m.MediaResolver(core.cfg());self.calls=0
  async def api(*args,**kwargs):self.calls+=1;return {'base64':base64.b64encode(png()).decode()}
  self.api=api
 async def asyncTearDown(self):await self.resolver.close()
 async def test_seen_reference_skips_download_but_followup_reuses_cached_pixels(self):
  row=image();first=await self.resolver.prepare([row],self.api,pending=[row],context=scope())
  receipt=first.receipts[0];known={receipt['identity']:{'summary':'红色测试方块'},receipt['digest']:{'summary':'红色测试方块'}}
  second=await self.resolver.prepare([row],self.api,pending=[row],context=scope(seen=known))
  self.assertFalse(second.images);self.assertEqual(self.calls,1);self.assertIn('红色测试方块',second.notes)
  third=await self.resolver.prepare([row],self.api,pending=[row],context=scope(['1'],known))
  self.assertEqual(len(third.images),1);self.assertEqual(self.calls,1)
 async def test_content_hash_dedup_rotated_reference_and_same_turn(self):
  a=image();b=image('2',file='changed.png')
  first=await self.resolver.prepare([a,b],self.api,pending=[a,b],context=scope())
  self.assertEqual(len(first.images),1);self.assertEqual(self.calls,2)
  receipt=first.receipts[0];known={receipt['digest']:{'summary':'同一张图'}}
  c=image('3',file='third.png')
  second=await self.resolver.prepare([c],self.api,pending=[c],context=scope(seen=known))
  self.assertFalse(second.images);self.assertEqual(second.receipts[0]['digest'],receipt['digest'])
 async def test_cache_is_bounded_and_never_crosses_chats(self):
  a=image();await self.resolver.prepare([a],self.api,context=scope(['1']))
  b=image(key='100:group:99');other=dict(scope(['1']),key='100:group:99')
  await self.resolver.prepare([b],self.api,context=other)
  self.assertEqual(self.calls,2)
  self.resolver.cfg.agent_chat_image_cache_bytes=0
  await self.resolver.prepare([a],self.api,context=scope(['1']))
  self.assertEqual(self.calls,3);self.assertEqual(self.resolver.cache_bytes,0)
 async def test_generic_filename_in_a_new_message_cannot_reuse_stale_pixels(self):
  a=image('1',file='image.png');b=image('2',file='image.png')
  await self.resolver.prepare([a],self.api,context=scope(['1']))
  await self.resolver.prepare([b],self.api,context=scope(['2']))
  self.assertEqual(self.calls,2)
 async def test_failures_never_return_read_receipts(self):
  async def fail(*a,**kw):raise RuntimeError('PRIVATE')
  result=await self.resolver.prepare([image()],fail,context=scope(['1']))
  self.assertEqual(result.receipts,[]);self.assertNotIn('PRIVATE',result.notes)

class ReceiptTests(unittest.IsolatedAsyncioTestCase):
 asyncSetUp=core.ServiceTests.asyncSetUp
 asyncTearDown=core.ServiceTests.asyncTearDown
 send=core.ServiceTests.send
 async def test_completed_read_survives_restart_and_plain_next_turn_has_no_image(self):
  resolver=m.MediaResolver(core.cfg());calls=[];attachments=[]
  async def api(*a,**kw):calls.append(1);return {'base64':base64.b64encode(png()).decode()}
  async def prepare(history,pending,context):return await resolver.prepare(history,api,pending=pending,context=context)
  original=self.client.reply
  async def reply(sid,text,images=None,**kwargs):attachments.append(len(images or []));return await original(sid,text,images,**kwargs)
  self.client.reply=reply
  async def turn(row):
   msg=core.domain.ChatMessage(**row);self.service.observe(msg);self.service.schedule(msg,self.send,prepare)
   await asyncio.gather(*list(self.service.tasks.values()))
  try:
   self.client.answer='QQ_REPLY '+json.dumps({'text':'红色方块','reply_to':'1','faces':[],
      'image_notes':{'qq-image-1.jpg':'红色背景，未见人物。'}},ensure_ascii=False)
   await turn(image(directed=True));key='100:group:42';sid=self.client.created[0]
   records=self.store.image_records(key,sid);self.assertTrue(records)
   self.assertTrue(all(v['summary']=='红色背景，未见人物。' for v in records.values()))
   self.assertEqual(str(self.sent[0]),'红色方块');self.assertNotIn('未见人物',str(self.sent[0]))
   path=self.store.db.execute('PRAGMA database_list').fetchone()[2]
   await self.service.close();self.store=core.Store(path);self.service=core.ChatService(core.cfg(),self.store,self.client)
   self.assertEqual(self.store.image_records(key,sid),records)
   self.client.answer='晚上好';await turn(core.message(mid='2').payload())
   self.assertEqual(attachments,[1,0]);self.assertEqual(len(calls),1)
   self.client.error=core.dsh.BridgeError('dsh_stream_disconnected')
   await turn(image('3',file='new.png',directed=True))
   self.assertEqual(self.store.image_records(key,sid),records)
   self.assertEqual(self.store.image_records('100:group:99',sid),{})
   self.assertEqual(self.store.image_records(key,'another-session'),{})
  finally:await resolver.close()

 async def test_image_rejected_before_admission_does_not_create_receipt(self):
  calls=[]
  async def prepare(*args):return m.PreparedMedia([{'name':'qq-image-1.jpg'}],'',
    [dict(identity='ref',digest='sha',message_id='1',name='qq-image-1.jpg')])
  async def reply(sid,text,images=None,**kwargs):
   calls.append(bool(images))
   if images:raise core.dsh.ImageUnsupported('model_does_not_support_images')
   return '现在看不了图片'
  self.client.reply=reply
  msg=core.message(mid='1');self.service.observe(msg);self.service.schedule(msg,self.send,prepare)
  await asyncio.gather(*list(self.service.tasks.values()))
  self.assertEqual(calls,[True,False])
  self.assertEqual(self.store.image_records(msg.key,self.client.created[0]),{})

class NotesTests(unittest.TestCase):
 def test_private_notes_cannot_create_qq_segments_or_arbitrary_image_targets(self):
  obj={'text':'看到了','reply_to':'','faces':[],'image_notes':{'qq-image-1.jpg':'[CQ:at,qq=all]'}}
  result=p.parse('QQ_REPLY '+json.dumps(obj),set(),images=[{'name':'qq-image-1.jpg'}])
  self.assertEqual(result.image_notes,obj['image_notes']);self.assertNotIn('CQ',json.dumps(p.segments(result)))
  self.assertFalse(p.parse('QQ_REPLY '+json.dumps(obj),set()))
  for bad in [{'file:///secret':'x'},{'qq-image-1.jpg':'x'*201},['bad']]:
   obj['image_notes']=bad;self.assertFalse(p.parse('QQ_REPLY '+json.dumps(obj),set(),images=[{'name':'qq-image-1.jpg'}]))
