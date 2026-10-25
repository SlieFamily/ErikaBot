// Host-side enforcement. A QQ prompt can never grant a capability.
// ToolRegistry API reference: DeepSeek Harness; qq-bridge's guard pattern (MIT).
export const name = 'erika-agent-chat-guard';
export const inject = ['tools'];

export function apply(ctx) {
  if (typeof ctx.tools?.guard !== 'function' || typeof ctx.tools?.restrict !== 'function') {
    throw new Error('agent_chat requires tools.guard and scoped tools.restrict');
  }
  // Deny *all* execution, including newly installed tools, MCP resources,
  // subagents, plugin installation, shell, files and Code Mode capabilities.
  ctx.tools.guard(() => 'agent_chat: tool execution is disabled');
  // Empty allowlist also hides inherited tools, including future tool names.
  // Do not catch: an unsupported/unscoped API must prevent preset creation.
  ctx.tools.restrict({allow: []});
}
