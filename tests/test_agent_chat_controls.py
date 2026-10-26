"""Regression tests for real QQ clock skew, quiet waiting and bulk moderation."""
import asyncio,importlib,json,sqlite3,time,unittest
from dataclasses import replace
import test_agent_chat as core
view=importlib.import_module(core.PACKAGE+'.presentation')
k=importlib.import_module(core.PACKAGE+'.knowledge')
admin=importlib.import_module(core.PACKAGE+'.knowledge_admin')
KEY='100:group:42';OTHER='100:group:43'

class QuoteClockTests(unittest.TestCase):
    def test_qq_clock_skew_is_consistent_with_admission_but_scope_is_bounded(self):
        now=time.time()
        messages=[replace(core.message(mid='1971989165'),timestamp=now+1.326).payload(),
            replace(core.message(mid='2'),timestamp=now+121).payload(),
            replace(core.message(mid='3'),timestamp=now-601).payload(),
            core.message(key=OTHER,mid='4').payload(),core.message(mid='invalid').payload()]
        targets=view.reply_targets(messages,KEY,now)
        self.assertEqual(targets,{'1971989165'})
        result=view.parse('QQ_REPLY '+json.dumps({'text':'好呀😏','reply_to':'1971989165','faces':['捂脸']}),targets)
        self.assertEqual(view.segments(result),[{'type':'reply','data':{'id':'1971989165'}},
            {'type':'text','data':{'text':'好呀😏'}},{'type':'face','data':{'id':'264'}}])

class QuietAndQuoteTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=core.ServiceTests.asyncSetUp
    asyncTearDown=core.ServiceTests.asyncTearDown
    submit=core.ServiceTests.submit
    send=core.ServiceTests.send

    async def test_future_timestamp_quote_survives_full_chat_service(self):
        self.client.answer='QQ_REPLY '+json.dumps({'text':'好呀😏','reply_to':'1971989165','faces':['捂脸']})
        await self.submit(replace(core.message(mid='1971989165'),timestamp=time.time()+2))
        self.assertEqual(self.sent[0].reply_to,'1971989165')
        self.assertEqual(self.sent[0].faces,(264,))
        self.assertIn('😏',self.sent[0])

    async def test_default_waiting_remains_quiet_until_final_answer(self):
        self.assertEqual(self.service.cfg.agent_chat_notice_after,0)
        entered,release=asyncio.Event(),asyncio.Event();original=self.client.reply
        async def slow(*args,**kwargs):
            entered.set();await release.wait();return await original(*args,**kwargs)
        self.client.reply=slow
        message=core.message();self.service.observe(message);self.service.schedule(message,self.send)
        await asyncio.wait_for(entered.wait(),2)
        self.assertFalse(self.service.notice_tasks)
        self.assertEqual(self.sent,[])
        release.set();await asyncio.wait_for(asyncio.gather(*list(self.service.tasks.values())),2)
        self.assertEqual(self.sent,['你好呀'])

class BulkConfirmationTests(unittest.TestCase):
    def setUp(self):self.db=sqlite3.connect(':memory:');self.store=k.KnowledgeStore(self.db)
    def tearDown(self):self.db.close()
    def candidate(self,term,meaning='',key=KEY):
        item=self.store.submit_slang(key,term,[{'key':key,'message_id':term,'text':term,'name':'群友','user_id':'7'}])
        with self.db:self.db.execute('UPDATE knowledge_slang SET meaning=? WHERE id=?',(meaning,item['id']))
        return item['id']
    def meanings(self):return {r[0]:r[1:] for r in self.db.execute('SELECT id,meaning,status FROM knowledge_slang')}

    def test_many_drafts_keep_individual_meanings_and_deduplicate(self):
        a=self.candidate('甲词','甲解释');b=self.candidate('乙词','乙解释')
        out=admin.handle(self.store,KEY,f'黑话确认 #{a}，{b}、{a}')
        self.assertIn('已确认 2 条',out)
        self.assertEqual(self.meanings(),{a:('甲解释','confirmed'),b:('乙解释','confirmed')})

    def test_missing_meaning_and_foreign_candidate_report_per_item(self):
        a=self.candidate('有解释','解释');b=self.candidate('无解释');c=self.candidate('其他群词','私有草稿',OTHER)
        out=admin.handle(self.store,KEY,f'黑话确认 {a} {b} {c} 999')
        self.assertIn('已确认 1 条',out);self.assertIn('缺少解释',out);self.assertIn('不属于当前群',out)
        self.assertNotIn('其他群词',out);self.assertNotIn('私有草稿',out)
        self.assertEqual(self.meanings()[b][1],'candidate');self.assertEqual(self.meanings()[c][1],'candidate')

    def test_multiline_explanations_and_single_legacy_are_supported(self):
        a=self.candidate('甲词');b=self.candidate('乙词')
        out=admin.handle(self.store,KEY,f'黑话确认\n{a} | 数字也可作解释233\n#{b} | 另一个解释')
        self.assertIn('已确认 2 条',out)
        self.assertEqual(self.meanings()[b],('另一个解释','confirmed'))
        self.assertIn('已确认 1 条',admin.handle(self.store,KEY,f'黑话确认 {a} 修改后的解释'))
        self.assertEqual(self.meanings()[a],('修改后的解释','confirmed'))

    def test_malformed_or_oversized_batch_has_no_partial_side_effects(self):
        a=self.candidate('甲词','解释')
        for tail in [f'{a},broken',f'{a} | 新解释\nbroken',f'{a} | 一\n{a} | 二',','.join(str(i) for i in range(1,32))]:
            with self.subTest(tail=tail):
                self.assertIn('操作未完成',admin.handle(self.store,KEY,'黑话确认 '+tail))
                self.assertEqual(self.meanings()[a],('解释','candidate'))

    def test_bad_explanation_does_not_block_other_valid_rows(self):
        a=self.candidate('甲词');b=self.candidate('乙词')
        out=admin.handle(self.store,KEY,f'黑话确认\n{a} | '+('长'*301)+f'\n{b} | 好解释')
        self.assertIn('已确认 1 条',out);self.assertEqual(self.meanings()[a][1],'candidate')
        self.assertEqual(self.meanings()[b],('好解释','confirmed'))
