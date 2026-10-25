"""Optional cooperation with agent_chat; importing this never loads the AI plugin."""
CONTEXT_KEY = "_erika_agent_chat"


def ai_owns_mention(state):
    return bool(state.get(CONTEXT_KEY, {}).get("takeover"))


def mark_handled(state):
    bucket = state.get(CONTEXT_KEY)
    if bucket is not None:
        bucket["claimed"] = True
