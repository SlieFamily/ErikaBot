"""Memory forwards preserve complete entries, chat scope and safe literal rendering."""
import importlib,sqlite3,unittest
from test_agent_chat import PACKAGE
from test_agent_chat_knowledge import k,admin,KEY,OTHER
report=importlib.import_module(PACKAGE+'.memory_report')

class MemoryReportTests(unittest.TestCase):
 def setUp(self):self.db=sqlite3.connect(':memory:');self.store=k.KnowledgeStore(self.db)
 def tearDown(self):self.db.close()
 def text(self,result):return '\n'.join(result.nodes)
 def test_default_readable_whole_entries_no_ids_or_internal_tags(self):
  self.store.append_memory(KEY,'activeTopic','周末一起玩法环',{'participants':['小明'],'pendingQuestion':'周六还是周日'})
  self.store.append_memory(KEY,'activeTopic','讨论新游戏')
  self.store.append_memory(KEY,'pendingThought','找机会聊聊新作')
  self.store.append_memory(KEY,'memberImpression','喜欢FPS',{'target':'7'},{'7':'小明'})
  self.store.append_memory(OTHER,'activeTopic','别群私人话题')
  before=self.db.execute('SELECT * FROM knowledge_memory ORDER BY id').fetchall()
  value=admin.handle(self.store,KEY,'记忆');text=self.text(value)
  for word in ('最近在聊的事','想接着聊的事','对群友的印象','小明：喜欢FPS','还没聊完：周六还是周日'):self.assertIn(word,text)
  for hidden in ('activeTopic','pendingThought','memberImpression','interactionCount','删除编号','别群私人话题'):self.assertNotIn(hidden,text)
  self.assertNotRegex(text,r'#\d+')
  self.assertIn('讨论新游戏\n\n周末一起玩法环',text)
  self.assertEqual(before,self.db.execute('SELECT * FROM knowledge_memory ORDER BY id').fetchall())
  self.assertEqual(self.store.learning_count(),0)
 def test_optional_management_keeps_single_item_deletion_working(self):
  self.store.append_memory(KEY,'activeTopic','要删的旧话题')
  i=self.store.memory(KEY)[0]['id']
  self.assertIn(f'删除编号 {i}',self.text(admin.handle(self.store,KEY,'记忆 管理')))
  self.assertIn('1 条',admin.handle(self.store,KEY,f'忘记 {i}'))
  self.assertIsInstance(admin.handle(self.store,KEY,'记忆'),str)
 def test_filter_aliases_invalid_pages_and_empty_state(self):
  self.assertIn('没有有效',admin.handle(self.store,KEY,'记忆'))
  self.store.append_memory(KEY,'activeTopic','当前话题')
  self.store.append_memory(KEY,'pendingThought','一个想法')
  for name in ('话题','activeTopic'):
   result=admin.handle(self.store,KEY,'记忆 '+name);self.assertEqual(result.entries,1);self.assertNotIn('一个想法',self.text(result))
  for tail in ('0','-1','2 3','话题 群友','管理 管理','不存在','1;bash'):
   self.assertEqual(report.build_memory_report(self.store,KEY,tail),report.USAGE)
  self.assertIn('只有 1 页',report.build_memory_report(self.store,KEY,'2'))
 def test_paging_has_no_truncation_or_missing_entries(self):
  for uid in range(50):
   for n in range(10):self.store.append_memory(KEY,'memberImpression',f'特征{n}'+('长'*45),{'target':str(uid)},{str(uid):f'成员{uid}号'})
  first=report.build_memory_report(self.store,KEY,'群友');self.assertGreater(first.pages,1)
  text=[]
  for page in range(1,first.pages+1):
   value=report.build_memory_report(self.store,KEY,f'群友 {page}')
   self.assertLessEqual(len(value.nodes),10);self.assertTrue(all(len(n)<=1800 for n in value.nodes))
   text.extend(value.nodes[1:])
  text='\n'.join(text);self.assertGreater(len(text),3500)
  for uid in range(50):self.assertEqual(text.count(f'成员{uid}号：'),1)
  self.assertIn('下一页：ai 记忆 群友 2',self.text(first))
 def test_expired_entries_are_not_presented(self):
  self.store.append_memory(KEY,'activeTopic','已过期的话题')
  with self.db:self.db.execute('UPDATE knowledge_memory SET expires=1')
  self.assertIn('没有有效',report.build_memory_report(self.store,KEY,''))

if __name__=='__main__':unittest.main()
