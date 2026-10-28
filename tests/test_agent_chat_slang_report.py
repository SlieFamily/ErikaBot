"""Cross-group moderator scope, bounded forward pages, and source privacy."""
import importlib,sqlite3,unittest
from test_agent_chat import PACKAGE
from test_agent_chat_knowledge import k,admin,KEY,OTHER
report=importlib.import_module(PACKAGE+'.slang_report')

class SlangReportTests(unittest.TestCase):
 def setUp(self):self.db=sqlite3.connect(':memory:');self.store=k.KnowledgeStore(self.db)
 def tearDown(self):self.db.close()
 def add(self,term,key=KEY,n=2,meaning='测试词义'):
  result=self.store.submit_slang(key,term,[dict(key=key,message_id=f'{term}-{i}',text='不应外发的原聊天：'+term,name='私人昵称',user_id='771122') for i in range(n)])
  with self.db:self.db.execute('UPDATE knowledge_slang SET meaning=? WHERE id=?',(meaning,result['id']))
  return result['id']
 def text(self,value):return '\n'.join(value.nodes)
 def test_all_groups_high_frequency_sorted_and_no_chat_identity_leak(self):
  a=self.add('高频甲',n=5);self.add('低频乙',n=1);b=self.add('另群丙',key=OTHER,n=3)
  self.add('其他机器人私词',key='101:group:42',n=10)
  page=report.build_report(self.store,'100','');text=self.text(page)
  self.assertIn('来源群 42',text);self.assertIn('来源群 43',text);self.assertIn(f'#{a}',text);self.assertIn(f'#{b}',text)
  for excluded in ['低频乙','其他机器人私词','不应外发的原聊天','私人昵称','771122']:self.assertNotIn(excluded,text)
  self.assertEqual(page.entries,2);self.assertIn('不是全量聊天词频',text)
 def test_shared_term_repeats_under_sources_with_one_global_id(self):
  entry=self.add('重复黑话',key=KEY,n=3);self.add('重复黑话',key=OTHER,n=2)
  value=report.build_report(self.store,'100','')
  self.assertEqual(value.entries,1);self.assertEqual(self.text(value).count(f'#{entry} 重复黑话'),2)
  self.assertIn('本群留存来源 3 条',self.text(value));self.assertIn('本群留存来源 2 条',self.text(value))
 def test_local_group_report_excludes_other_origins_even_with_all(self):
  shared=self.add('两群共有词',key=KEY,n=3);self.add('两群共有词',key=OTHER,n=2)
  local=self.add('本群低频词',key=KEY,n=1);self.add('另群独有词',key=OTHER,n=5)
  self.store.add_manual_slang('无来源手工词','全局解释')
  value=admin.handle(self.store,KEY,'黑话 全部',admin_bot='100',report_key=KEY)
  text=self.text(value)
  self.assertIn('当前群 42',text);self.assertIn('来源群 42',text)
  self.assertIn(f'#{local}',text);self.assertEqual(text.count(f'#{shared} 两群共有词'),1)
  for token in ('来源群 43','另群独有词','无来源手工词','本群留存来源 2 条'):
   self.assertNotIn(token,text)
  self.assertEqual(value.entries,2)
  central=self.text(admin.handle(self.store,'100:group:999','黑话 全部',admin_bot='100'))
  self.assertIn('来源群 43',central);self.assertIn('无来源手工词',central)
 def test_local_empty_group_never_falls_back_to_global(self):
  self.add('别群词',key=OTHER,n=3)
  self.assertIn('暂无',report.build_report(self.store,'100','全部',chat_key=KEY))
  with self.assertRaises(ValueError):report.build_report(self.store,'100','',chat_key='101:group:43')
 def test_status_low_frequency_and_manual_sections(self):
  a=self.add('待确认词',n=1);b=self.add('已确认词',n=3);c=self.add('已拒绝词',n=4)
  self.store.review_slang(KEY,b,'confirm');self.store.review_slang(KEY,c,'reject')
  self.store.add_manual_slang('手工词','手工解释')
  default=self.text(report.build_report(self.store,'100',''))
  self.assertIn('已确认词',default);self.assertIn('已拒绝词',default);self.assertNotIn('待确认词',default)
  pending=self.text(report.build_report(self.store,'100','候选 全部'))
  self.assertIn('待确认词',pending);self.assertNotIn('已确认词',pending)
  self.assertIn('共享手工词条',self.text(report.build_report(self.store,'100','全部')))
 def test_pages_cover_every_complete_entry_without_sending_every_page(self):
  ids=[]
  for i in range(64):ids.append(self.add('分页词'+str(i),meaning='含义'*150))
  first=report.build_report(self.store,'100','候选');self.assertGreater(first.pages,1);all_text=[]
  for page in range(1,first.pages+1):
   result=report.build_report(self.store,'100',f'候选 {page}')
   self.assertLessEqual(len(result.nodes),report.CHUNKS_PER_PAGE+1)
   self.assertTrue(all(len(node)<=report.MAX_NODE_CHARS for node in result.nodes))
   all_text.extend(result.nodes[1:])
  text='\n'.join(all_text)
  for i in ids:self.assertEqual(text.count(f'#{i} 分页词'),1)
  self.assertIn('下一页：ai 黑话 候选 2',self.text(first))
  self.assertIsInstance(report.build_report(self.store,'100',str(first.pages+1)),str)
 def test_invalid_options_empty_results_and_untrusted_cq_remain_data(self):
  for value in ['0','-1','2 3','候选 已确认','全部 全部','全群','99999999','1;bash']:
   self.assertEqual(report.build_report(self.store,'100',value),report.USAGE)
  self.assertIn('暂无',report.build_report(self.store,'100',''))
  self.add('普通词',meaning='字面讨论 [CQ:at,qq=all]')
  # Bypass persisted validation only to exercise output safety; NoneBot probe checks literal segment wire shape.
  self.assertIn('[CQ:at',self.text(report.build_report(self.store,'100','')))
 def test_global_review_uses_actual_bot_not_destination_and_keeps_meanings(self):
  a=self.add('甲群词',meaning='甲解释');b=self.add('乙群词',key=OTHER,meaning='乙解释')
  c=self.add('别号词',key='101:group:42',meaning='别号解释');d=self.add('无解释词',key=OTHER,meaning='')
  value=admin.handle(self.store,'100:group:999',f'黑话确认 {a} {b} {c} {d} 9999',admin_bot='100')
  self.assertIn('已确认 2 条',value);self.assertIn('缺少解释',value);self.assertNotIn('别号词',value)
  rows={i:(m,s) for i,m,s in self.db.execute('SELECT id,meaning,status FROM knowledge_slang')}
  self.assertEqual(rows[a],('甲解释','confirmed'));self.assertEqual(rows[b],('乙解释','confirmed'))
  self.assertEqual(rows[c][1],'candidate')
  self.assertEqual(self.store.learning_count(),0)
 def test_global_reject_delete_manual_and_original_local_scope(self):
  entry=self.add('别群词',key=OTHER)
  with self.assertRaises(k.KnowledgeError):self.store.review_slang(KEY,entry,'confirm')
  self.assertIn('已处理',admin.handle(self.store,'100:group:999',f'黑话拒绝 {entry}',admin_bot='100'))
  self.assertIn('已处理',admin.handle(self.store,'100:group:999',f'黑话删除 {entry}',admin_bot='100'))
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM knowledge_seen WHERE slang_id=?',(entry,)).fetchone()[0],0)
 def test_origin_group_survives_evidence_rotation_and_bot_validation(self):
  entry=self.add('跨群轮换词',n=2)
  self.add('跨群轮换词',key=OTHER,n=20)
  self.assertFalse(self.db.execute('SELECT 1 FROM knowledge_evidence WHERE slang_id=? AND chat_key=?',(entry,KEY)).fetchone())
  self.assertIn('来源群 42',self.text(report.build_report(self.store,'100','')))
  for bot in ['100%',"100' OR 1=1",'100:group:42']:
   with self.assertRaises(k.KnowledgeError):self.store.slang_report_rows(bot)

if __name__=='__main__':unittest.main()
