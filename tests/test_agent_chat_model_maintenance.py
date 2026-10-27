import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import manage_agent_chat_models as model

TARGET={'provider':'mx','model':'flash'}
OLD={'provider':'old','model':'old'}
class FakeClient:
    def __init__(self):
        self.models={'chat':dict(OLD),'worker':dict(OLD)}
        self.default=dict(OLD);self.busy=set();self.fail={};self.selected=[];self.audited=[]
    async def rpc(self,method,payload=None):
        if method=='session/modelCatalog':return {'default':self.default,'groups':[{'id':'mx','models':[{'id':'flash','reasoning':{'efforts':[{'id':'off'}]}}]}]}
        if method=='session/list':return {'items':[{'sessionId':s,'running':s in self.busy} for s in self.models]}
        sid=payload['sessionId']
        if method=='session/projections':return {'values':{'modelSelection':{'next':dict(self.models[sid])},'inbox':{'next-turn':[],'next-step':[]}}}
        if method=='session/selectModel':
            self.selected.append(sid)
            self.models[sid]={k:v for k,v in payload.items() if k!='sessionId'}
            self.default=dict(self.models[sid]);return {'selected':self.default}
        raise AssertionError(method)
    async def recovery_checkpoint(self,sid):
        self.audited.append(sid)
        if sid in self.fail:raise model.dsh.BridgeError(self.fail[sid])
        if sid in self.busy:raise model.dsh.BridgeError('recovery_turn_active')
        return 20

class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'switch.json'
        self.rows=[dict(family='chat',chat='1:group:42',sid='chat',policy='p',suspended=False),dict(family='slang',chat='1:group:42',sid='worker',policy='w',suspended=False)]
        self.client=FakeClient();self.clients=dict(chat=self.client,slang=self.client,memory=self.client)
    async def asyncTearDown(self):self.tmp.cleanup()
    async def run_switch(self,**kwargs):
        return await model.switch_bound(self.clients,lambda:copy.deepcopy(self.rows),kwargs.pop('archived',set()),kwargs.pop('target',TARGET),report_path=self.path,**kwargs)
    async def test_read_only_status_and_plan_do_not_mutate(self):
        for target in (None,TARGET):
            report=await self.run_switch(target=target)
            self.assertTrue(report['complete'])
        self.assertEqual(self.client.selected,[]);self.assertFalse(self.path.exists())
    async def test_switch_keeps_bindings_and_records_rollback(self):
        before=copy.deepcopy(self.rows)
        report=await self.run_switch(apply=True)
        self.assertTrue(report['complete']);self.assertEqual(self.rows,before)
        self.assertEqual(self.client.selected,['chat','worker'])
        saved=json.loads(self.path.read_text(encoding='utf8'))
        self.assertEqual(saved['default_before']['provider'],'old')
        self.assertTrue(all(r['before']==OLD for r in saved['sessions']))
        self.assertTrue(all(r['status']=='selected' for r in saved['sessions']))
    async def test_busy_foreign_and_archived_are_never_changed(self):
        self.client.busy.add('chat');self.client.fail['worker']='recovery_foreign_input'
        report=await self.run_switch(apply=True)
        self.assertFalse(report['complete']);self.assertEqual(self.client.selected,[])
        self.path.unlink();self.client.busy.clear();self.client.fail.clear()
        report=await self.run_switch(apply=True,archived={'chat','worker'})
        self.assertFalse(report['complete']);self.assertEqual(self.client.selected,[])
    async def test_already_selected_aligns_default_after_idle_audit(self):
        self.client.models={s:dict(TARGET) for s in self.client.models}
        report=await self.run_switch(apply=True)
        self.assertTrue(report['complete']);self.assertEqual(self.client.selected,['chat'])
        self.assertIn('chat',self.client.audited)
    async def test_changing_binding_is_not_selected(self):
        n=0
        def read():
            nonlocal n
            n+=1
            return copy.deepcopy(self.rows) if n==1 else []
        report=await model.switch_bound(self.clients,read,set(),TARGET,True,self.path)
        self.assertFalse(report['complete']);self.assertEqual(self.client.selected,[])
    async def test_suspension_is_reported_and_preserved(self):
        self.rows[0]['suspended']=True
        report=await self.run_switch(apply=True)
        self.assertTrue(self.rows[0]['suspended']);self.assertTrue(report['sessions'][0]['suspended'])
    async def test_invalid_model_and_reasoning_are_rejected(self):
        cat=await self.client.rpc('session/modelCatalog')
        for target in ({'provider':'other','model':'flash'},{**TARGET,'reasoningEffort':'imaginary'}):
            with self.assertRaises(model.dsh.BridgeError):model.validate_target(cat,target)
        model.validate_target(cat,{**TARGET,'reasoningEffort':'off'})
    async def test_catalog_has_no_request_argument_or_secret_output(self):
        def handle(request):
            body=json.loads(request.content)
            self.assertEqual(body['payload']['args'],{})
            return httpx.Response(200,json={'type':'server-response','rpcId':body['rpcId'],'result':{'ok':True,'value':{'groups':[]}}})
        from check_agent_chat import package
        import importlib
        cfg=importlib.import_module(package.__name__+'.config').Config(agent_chat_dsh_cookie='dsh-auth-test=private')
        client=model.dsh.DshClient(cfg,http=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        try:self.assertEqual(await client.rpc('session/modelCatalog'),{'groups':[]})
        finally:await client.close()
