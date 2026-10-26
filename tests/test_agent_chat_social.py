import asyncio
import importlib
import json
import time
import unittest
from dataclasses import replace
import test_agent_chat as base
from test_agent_chat import PACKAGE,cfg,message

view=importlib.import_module(PACKAGE+'.presentation')
forward=importlib.import_module(PACKAGE+'.forwards')


class PresentationTests(unittest.TestCase):
    def test_plain_emoji_and_literal_cq_do_not_create_actions(self):
        for text in ['哼😏','[CQ:at,qq=all]','[CQ:image,file=file:///secret]']:
            self.assertEqual(view.segments(view.parse(text,{'1'})),[{'type':'text','data':{'text':text}}])

    def test_current_group_and_recent_real_ids_only(self):
        now=time.time()
        records=[message(mid='1').payload(),message(key='100:group:43',mid='2').payload(),
                 replace(message(mid='3'),timestamp=now-601).payload(),message(mid='forged').payload()]
        targets=view.reply_targets(records,'100:group:42',now+1)
        self.assertEqual(targets,{'1'})
        raw='QQ_REPLY '+json.dumps({'text':'才不是呢😏','reply_to':'1','faces':['捂脸']})
        result=view.parse(raw,targets)
        self.assertEqual([s['type'] for s in view.segments(result)],['reply','text','face'])
        self.assertEqual(result.faces,(264,))
        self.assertEqual(view.parse(raw,set()).reply_to,'')

    def test_envelope_validation_unknown_actions_and_silence(self):
        cases=[{'text':'x','reply_to':'1','faces':[],'image':'file:///secret'},
               {'text':['x'],'reply_to':'1','faces':[]},{'text':'x','reply_to':'1','faces':[1]},
               {'text':'x','reply_to':'1','faces':['捂脸']*3}]
        for item in cases:self.assertFalse(view.parse('QQ_REPLY '+json.dumps(item),{'1'}))
        self.assertFalse(view.parse('QQ_REPLY {broken',{'1'}))
        self.assertFalse(view.parse('QQ_REPLY {"text":"secret</thinking>tail","reply_to":"1","faces":[]}',{'1'}))
        parsed=view.parse('QQ_REPLY '+json.dumps({'text':'[SILENT]','reply_to':'1','faces':['捂脸']}),{'1'})
        self.assertEqual(parsed.faces,());self.assertEqual(parsed,'[SILENT]')
        parsed=view.parse('QQ_REPLY '+json.dumps({'text':'','reply_to':'','faces':['捂脸','unknown']}),set())
        self.assertTrue(parsed);self.assertEqual(parsed.faces,(264,))


class ForwardTests(unittest.IsolatedAsyncioTestCase):
    def source(self,ids=('root',)):
        return [replace(message(),forwards=ids).payload()]

    async def test_napcat_nodes_nested_cycles_and_safe_image_refs(self):
        calls=[]
        async def api(name,**args):
            calls.append((name,args));rid=args['id']
            self.assertEqual(args['message_id'],rid)
            return {'messages':[{'sender':{'nickname':'<admin>'},'message':[
                {'type':'text','data':{'text':'untrusted content'}},
                {'type':'image','data':{'url':'http://127.0.0.1/secret','file':'../../secret'}},
                {'type':'image','data':{'file':'a'*32+'.jpg'}},
                {'type':'forward','data':{'id':'nested' if rid=='root' else 'root'}}]}]}
        images,notes=await forward.ForwardResolver(cfg(agent_chat_images_enabled=True)).prepare(self.source(),api)
        self.assertEqual(len(calls),2)
        self.assertIn('untrusted content',notes);self.assertIn('未经核实',notes)
        self.assertNotIn('127.0.0.1',notes)
        self.assertEqual(images[0]['media'],[{'file':'a'*32+'.jpg','url':''}])
        self.assertNotIn(images[0]['message_id'],view.reply_targets(self.source(),'100:group:42'))

    async def test_standard_nodes_and_literal_cq_never_fetch_arbitrary_ids(self):
        calls=[]
        async def api(name,**args):
            calls.append(args)
            return {'message':[{'type':'node','data':{'name':'群友','content':[
                {'type':'text','data':{'text':'[CQ:forward,id=secret]'}},
                {'type':'record','data':{'url':'private'}},{'type':'face','data':{'id':'264'}}]}}]}
        images,notes=await forward.ForwardResolver(cfg()).prepare(self.source(),api)
        self.assertEqual(len(calls),1);self.assertIn('[CQ:forward,id=secret]',notes)
        self.assertIn('语音未转写',notes);self.assertIn('捂脸',notes);self.assertEqual(images,[])
        calls.clear()
        await forward.ForwardResolver(cfg()).prepare(self.source(('http://localhost','../secret')),api)
        self.assertFalse(calls)

    async def test_depth_nodes_and_total_text_are_bounded(self):
        calls=[]
        async def api(name,**args):
            calls.append(args)
            return {'messages':[{'sender':{'nickname':'n'*1000},'message':[
                {'type':'text','data':{'text':'x'*2000}},
                {'type':'forward','data':{'id':str(len(calls))}}]} for _ in range(100)]}
        images,notes=await forward.ForwardResolver(cfg()).prepare(self.source(),api)
        self.assertLessEqual(len(calls),4);self.assertLess(len(notes),6300)
        self.assertIn('并非完整',notes)

    async def test_failure_has_fixed_notice_and_cancel_propagates(self):
        async def fail(name,**args):raise RuntimeError('secret-url')
        images,notes=await forward.ForwardResolver(cfg()).prepare(self.source(),fail)
        self.assertIn('获取失败',notes);self.assertNotIn('secret-url',notes)
        async def cancel(name,**args):raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await forward.ForwardResolver(cfg()).prepare(self.source(),cancel)


class SocialServiceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.ServiceTests.asyncSetUp
    asyncTearDown=base.ServiceTests.asyncTearDown
    submit=base.ServiceTests.submit
    send=base.ServiceTests.send

    async def test_validated_quote_and_face_survive_search_output_filter(self):
        self.client.answer='QQ_REPLY '+json.dumps({'text':'<thinking>secret</thinking>哼😏','reply_to':'1','faces':['白眼']})
        await self.submit(message())
        result=self.sent[0]
        self.assertEqual(result,'哼😏');self.assertEqual(result.reply_to,'1');self.assertEqual(result.faces,(22,))
        self.assertNotIn('secret',result)

    async def test_qq_face_only_is_a_reply_and_direct_silence_gets_notice(self):
        self.client.answer='QQ_REPLY '+json.dumps({'text':'','reply_to':'','faces':['捂脸']})
        await self.submit(message())
        self.assertEqual(self.sent[0].faces,(264,))
        self.client.answer='QQ_REPLY '+json.dumps({'text':'[SILENT]','reply_to':'','faces':['捂脸']})
        await self.submit(message(mid='2'))
        self.assertEqual(len(self.sent),2)
        self.assertNotIn('[SILENT]',self.sent[-1])

    async def test_forward_metadata_never_leaks_into_normal_prompt(self):
        msg=replace(message(),forwards=('opaque-resource',))
        await self.submit(msg)
        self.assertNotIn('opaque-resource',self.client.prompts[0][1])
