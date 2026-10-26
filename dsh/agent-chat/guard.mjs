// Host-side enforcement. A QQ prompt can never grant a capability.
// ToolRegistry API reference: DeepSeek Harness; qq-bridge's guard pattern (MIT).
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
    if (Object.keys(value).sort().join(',') !== 'enabled,expires,rpcId,sessionId,version' ||
        value.version !== 1 || value.sessionId !== session.id || value.rpcId !== source.rpcId ||
        typeof value.enabled !== 'boolean' || !Number.isSafeInteger(value.expires) ||
        value.expires < Date.now() || value.expires > Date.now() + 310_000) return null;
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
    agent.ctx.tools.restrict({allow: ['web_search']});
    admitted.add(agent);
  });
  ctx.tools.presentAs('native');
  const turns = new WeakMap();
  ctx.on('session/event', (session, event) => {
    if (event.type === 'turn/start') {
      turns.set(session, {turn: event.data.turn, control: null, calls: new Set()});
    } else if (event.type === 'turn/end') {
      turns.delete(session);
    } else if (event.type === 'user/message' && event.data?.source?.kind === 'user') {
      const state = turns.get(session);
      if (state) state.control = controlFor(session, event);
    }
  });
  ctx.tools.guard(exec => {
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
    state.calls.add(exec.callId);
  });
}
