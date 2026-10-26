// Host-side enforcement. A QQ prompt can never grant a capability.
// ToolRegistry API reference: DeepSeek Harness; qq-bridge's guard pattern (MIT).
import {registerKnowledge, knowledgeTools, memoryTools, slangTools} from './knowledge.mjs';
export const name = 'erika-agent-chat-guard';
export const inject = ['tools', 'web'];

export const CONTROL_PREFIX = 'QQ_BRIDGE_SEARCH_POLICY ';
const MAX_CALLS = 2;

export function publicQuery(value) {
  if (typeof value !== 'string') return false;
  const q = value.normalize('NFKC').trim();
  return q.length > 0 && q.length <= 120 && !/[\p{C}]/u.test(q) &&
    !/\d{5,}|https?:\/\/|file:|[A-Za-z]:[\\/]|\\\\|[\w.+-]+@[\w.-]+|api[_ -]?key|authorization|bearer|password|密码|口令|cookie|sk-[\w-]+/i.test(q);
}

function controlFor(session, event) {
  const source = event.data?.source;
  const block = event.data?.content?.[0];
  if (source?.kind !== 'user' || typeof source.rpcId !== 'string' ||
      event.surfaceOp !== 'append' || block?.type !== 'text' || !block.text.startsWith(CONTROL_PREFIX)) return null;
  try {
    const value = JSON.parse(block.text.split('\n', 1)[0].slice(CONTROL_PREFIX.length));
    if (Object.keys(value).some(k=>!['enabled','expires','rpcId','sessionId','version','knowledge','researchTerm'].includes(k)) ||
        value.version !== 1 || value.sessionId !== session.id || value.rpcId !== source.rpcId ||
        typeof value.enabled !== 'boolean' || !Number.isSafeInteger(value.expires) ||
        value.expires < Date.now() || value.expires > Date.now() + 310_000 ||
        (value.knowledge !== undefined && (!Array.isArray(value.knowledge) || value.knowledge.length > 2 ||
          value.knowledge.some(k=>!['memory','slang'].includes(k)))) ||
        (value.researchTerm !== undefined && (!publicQuery(value.researchTerm) || value.researchTerm.length > 50))) return null;
    return value;
  } catch { return null; }
}

export function apply(ctx) {
  if (typeof ctx.tools?.guard !== 'function' || typeof ctx.tools?.restrict !== 'function' ||
      typeof ctx.tools?.presentAs !== 'function' || typeof ctx.on !== 'function') {
    throw new Error('agent_chat requires scoped native tools and session events');
  }
  const provider = () => ctx.web?.config?.searchProvider?.get?.() ?? ctx.web?.searchProviderEnv;
  if (provider() !== 'anysearch') throw new Error('agent_chat requires the installed AnySearch provider');
  // Restrict at the actual agent scope: preset-owned tools are inherited by
  // an agent, but are not restrictable globals while the preset is mounting.
  const admitted = new WeakSet();
  ctx.on('agent/created', ({agent}) => {
    // Preset tools become inherited (restrictable) at the descendant agent.
    agent.ctx.tools.restrict({allow: ['web_search',...knowledgeTools]});
    admitted.add(agent);
  });
  ctx.tools.presentAs('native');
  const turns = new WeakMap();
  const knowledgeControl = exec => {
    const state=turns.get(exec?.agent?.session), control=state?.control;
    const family=memoryTools.includes(exec?.name)?'memory':slangTools.includes(exec?.name)?'slang':'';
    return admitted.has(exec?.agent) && exec.parent===undefined && control?.expires>=Date.now() &&
      control.knowledge?.includes(family) && state.knowledgeCalls.has(exec.callId) ? control : null;
  };
  registerKnowledge(ctx,knowledgeControl);
  ctx.on('session/event', (session, event) => {
    if (event.type === 'turn/start') {
      turns.set(session, {turn: event.data.turn, control: null, calls: new Set(), knowledgeCalls:new Set()});
    } else if (event.type === 'turn/end') {
      turns.delete(session);
    } else if (event.type === 'user/message' && event.data?.source?.kind === 'user') {
      const state = turns.get(session);
      if (state) state.control = controlFor(session, event);
    }
  });
  ctx.tools.guard(exec => {
    if (knowledgeTools.includes(exec?.name) && admitted.has(exec.agent) && exec.parent===undefined) {
      const state=turns.get(exec.agent.session), control=state?.control;
      const family=memoryTools.includes(exec.name)?'memory':'slang';
      if (!control?.knowledge?.includes(family) || control.expires<Date.now() ||
          typeof exec.callId!=='string' || state.knowledgeCalls.has(exec.callId) || state.knowledgeCalls.size>=6) {
        return 'agent_chat: knowledge tool is not authorized for this bridge request';
      }
      state.knowledgeCalls.add(exec.callId);
      return;
    }
    if (exec?.name !== 'web_search' || !admitted.has(exec.agent) || exec.parent !== undefined || provider() !== 'anysearch') {
      return 'agent_chat: only native AnySearch web_search is allowed';
    }
    const state = turns.get(exec.agent?.session);
    if (!state?.control?.enabled || state.control.expires < Date.now()) {
      return 'agent_chat: search is not authorized for this bridge request';
    }
    const args = exec.arguments;
    if (!args || Object.keys(args).join(',') !== 'queries' || !Array.isArray(args.queries) ||
        args.queries.length !== 1 || !publicQuery(args.queries[0])) {
      return 'agent_chat: use one public topic of at most 120 characters, without private data';
    }
    if (typeof exec.callId !== 'string' || state.calls.has(exec.callId) || state.calls.size >= MAX_CALLS) {
      return 'agent_chat: search limit reached; answer using existing evidence';
    }
    if (state.control.researchTerm && !['',' 是什么梗',' 网络用语 含义'].some(suffix=>
        args.queries[0].normalize('NFKC').trim()===state.control.researchTerm.normalize('NFKC')+suffix)) {
      return 'agent_chat: learner search is limited to the approved public term';
    }
    state.calls.add(exec.callId);
  });
}
