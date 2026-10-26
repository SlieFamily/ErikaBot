"""Opt-in isolated vision/cache/offload probe: four model turns, no QQ sends."""
import argparse,asyncio,base64,hashlib,importlib,io,json,sys,tempfile,time,uuid
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import load_config,dsh,package
core=lambda name:importlib.import_module(package.__name__+'.'+name)
from agent_chat_prompt_compact_probe import snapshot
async def run(path,require_vision=False):
 cfg=load_config(private_file=path).copy(update={'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),
  'agent_chat_proactive_enabled':False,'agent_chat_debounce':0,'agent_chat_cooldown':0,'agent_chat_search_enabled':False,
  'agent_chat_memory_enabled':False,'agent_chat_slang_enabled':False,'agent_chat_timeout':240,
  'agent_chat_ambient_probability':.2,'agent_chat_quiet_start':0,'agent_chat_quiet_end':0})
 assert cfg.agent_chat_dsh_url=='http://127.0.0.1:43125','isolated DSH required'
 picture=Image.new('RGB',(300,160),'white');draw=ImageDraw.Draw(picture)
 draw.rectangle((20,30,110,120),fill='red');draw.ellipse((190,30,280,120),fill='blue')
 output=io.BytesIO();picture.save(output,format='JPEG');raw=output.getvalue()
 media={'file':hashlib.md5(raw).hexdigest()+'.jpg'}
 downloads=[];sizes=[];sent=[];sid=None;key='100:group:42'
 async def api(*a,**kw):downloads.append(1);return {'base64':base64.b64encode(raw).decode()}
 async def send(value):sent.append(value)
 with tempfile.TemporaryDirectory() as folder:
  path=Path(folder)/'probe.db'
  store=core('store').Store(path);client=dsh.DshClient(cfg);service=core('service').ChatService(cfg,store,client)
  resolver=core('media').MediaResolver(cfg)
  def capture():
   original=client.reply
   async def record(sid,text,images=None,**kwargs):
    sizes.append(len(images or []));return await original(sid,text,images,**kwargs)
   client.reply=record
  capture()
  async def prepare(history,pending,context):return await resolver.prepare(history,api,pending=pending,context=context)
  async def turn(mid,text,pixels=False,directed=True):
   msg=core('domain').ChatMessage(key,mid,'7','测试群友',text,time.time(),directed,media=(media,) if pixels else ())
   service.observe(msg)
   with patch('random.random',return_value=0):assert service.schedule(msg,send,prepare)
   await asyncio.gather(*list(service.tasks.values()))
   bound=store.session(key);assert bound and not bound[2],'vision_turn_failed'
   return bound[0]
  try:
   sid=await turn('101','读图测试：只说图片左右分别是什么颜色和形状。',True)
   assert sizes==[1] and len(downloads)==1
   vision_confirmed='红' in str(sent[-1]) and '蓝' in str(sent[-1])
   if require_vision:assert vision_confirmed,'current_api_vision_or_reply_format_not_confirmed'
   elif not vision_confirmed:print('NOTE current API vision/reply format not confirmed; transport assertions continue separately',flush=True)
   first=await snapshot(client,sid)
   assert not any(r['event']['type']=='image/offload' for r in first['records']),'current_image_offloaded_early'
   assert any(any(b.get('type')=='image' for b in r['event'].get('data',{}).get('content',[])) for r in first['records']),'current_attachment_missing'
   assert store.image_records(key,sid),'image_receipt_missing'
   print('PASS first turn: attachment accepted, no current-turn omission, private receipt committed',flush=True)
   await turn('102','晚上好，随便打个招呼吧。')
   assert sizes==[1,0] and len(downloads)==1
   snap=await snapshot(client,sid)
   offloads=[r['event'] for r in snap['records'] if r['event']['type']=='image/offload']
   assert offloads,'native_offload_not_committed'
   assert any(t['imageIndexes']==[0] for e in offloads for t in e['data']['targets'])
   print('PASS ordinary text turn: zero new pixels; native offload committed for earlier pixels',flush=True)
   await turn('103','再看看图里的形状，只简短说左边和右边各是什么。')
   assert sizes==[1,0,1] and len(downloads)==1,'followup_did_not_reuse_image_cache'
   print('PASS explicit followup: original image reattached from local cache',flush=True)
   await service.close();await resolver.close()
   store=core('store').Store(path);client=dsh.DshClient(cfg);service=core('service').ChatService(cfg,store,client)
   resolver=core('media').MediaResolver(cfg);capture()
   reused=await turn('104','又转了这张给大家看看',True,False)
   assert reused==sid and sizes==[1,0,1,0] and len(downloads)==1,'durable_duplicate_detection_failed'
   assert not any('image_notes' in str(v) or 'qq-image-' in str(v) for v in sent),'private_image_protocol_leaked'
   print(json.dumps({'completed':4,'vision_recognition_confirmed':vision_confirmed,'images_per_turn':sizes,'image_downloads':len(downloads),
     'native_offload_verified':True,'restart_dedup_verified':True,'qq_sends':0,'production_sessions_touched':0}),flush=True)
   print('PASS: selective images, persistent dedup, bounded cache, explicit reread and native DSH offload',flush=True)
  finally:
   try:
    bound=store.session(key)
    if bound:await client.stop(bound[0])
   finally:await service.close();await resolver.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--env-file',required=True,type=Path)
 parser.add_argument('--confirm-model-calls',required=True,action='store_true')
 parser.add_argument('--require-vision',action='store_true',help='Also require correct first-turn visual recognition; API-dependent')
 args=parser.parse_args()
 try:asyncio.run(run(args.env_file,args.require_vision))
 except Exception as e:print('FAIL',type(e).__name__,str(e) if isinstance(e,(AssertionError,dsh.BridgeError)) else '');sys.exit(1)
