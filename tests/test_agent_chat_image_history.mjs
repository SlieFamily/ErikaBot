import assert from 'node:assert/strict';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {offloadPreviousImages} from '../dsh/agent-chat/image-history.mjs';
import {CONTROL_PREFIX} from '../dsh/agent-chat/guard.mjs';
function row(seq,{foreign=false,offloaded=false,assistant=false}={}) {
 const rpcId='r'+seq;
 return {seq,type:assistant?'assistant/message':'user/message',surfaceOp:'append',data:{source:{kind:'user',rpcId},
  content:[{type:'text',text:foreign?'foreign input':CONTROL_PREFIX+JSON.stringify({version:1,sessionId:'s',rpcId})},
           {type:'image',attachment:{id:'pic-'+seq},offloaded}]}};
}
function fixture() {
 const events=[row(0),row(1,{foreign:true}),row(2,{offloaded:true}),row(3),row(4,{assistant:true})];
 const records=[],projected=new Map();
 const session={id:'s',surface:{nodes:events.map(e=>e.seq)},eventAt:seq=>events[seq],
  deriveEventMessage:e=>projected.get(e.seq)||e.data,
  append:(type,data)=>{records.push({type,data});for(const t of data.targets)projected.set(t.seq,{...events[t.seq].data,
   content:events[t.seq].data.content.map(b=>b.type==='image'?{...b,offloaded:true}:b)});}};
 return {session,records,events};
}
test('only earlier bridge-owned image occurrences leave the current model context',()=>{
 const f=fixture();assert.equal(offloadPreviousImages(f.session,3,CONTROL_PREFIX),1);
 assert.deepEqual(f.records,[{type:'image/offload',data:{targets:[{seq:0,imageIndexes:[0]}]}}]);
 assert.equal(offloadPreviousImages(f.session,3,CONTROL_PREFIX),0);
 assert.equal(offloadPreviousImages(f.session,5,CONTROL_PREFIX),1);
 assert.equal(f.records[1].data.targets[0].seq,3);
});
test('unknown current turn and model/foreign input cannot offload history',()=>{
 const f=fixture();for(const seq of [undefined,-1,NaN,'3'])assert.equal(offloadPreviousImages(f.session,seq,CONTROL_PREFIX),0);
 f.events[0].data.content[0].text=CONTROL_PREFIX+JSON.stringify({version:1,sessionId:'other',rpcId:'r0'});
 assert.equal(offloadPreviousImages(f.session,3,CONTROL_PREFIX),0);assert.equal(f.records.length,0);
});
test('installed native DSH projection validates and preserves image references on replay',{
 skip:!process.env.AGENT_CHAT_TEST_DSH_ROOT},async()=>{
 const {imageOffloadProjection}=await import(pathToFileURL(process.env.AGENT_CHAT_TEST_DSH_ROOT+'/node_modules/@deepseek-ai/dsh-compaction-image-offload/lib/types/projection.js'));
 const f=fixture();offloadPreviousImages(f.session,3,CONTROL_PREFIX);
 const context={nodes:f.session.surface.nodes,events:f.events,baseSeq:0,messages:new Map()};
 const result=imageOffloadProjection.project(f.records[0],context);
 assert.equal(result.get(0).content[1].offloaded,true);
 assert.equal(result.get(0).content[1].attachment.id,'pic-0');assert(!result.has(3));
 assert.equal(f.events[0].data.content[1].offloaded,false);
 assert.throws(()=>imageOffloadProjection.project(f.records[0],{...context,messages:result}));
});
