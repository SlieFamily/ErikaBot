"""ErikaBot ↔ DSH bridge. Disabled unless explicitly configured by the owner."""
from typing import Optional

from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment, PrivateMessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.message import event_postprocessor, event_preprocessor, run_postprocessor
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State

from utils.agent_chat_routing import CONTEXT_KEY
from .config import load_config
from .domain import ChatMessage
from .dsh import BridgeError, DshClient
from .service import ChatService
from .store import Store


driver = get_driver()
config = load_config(driver.config.dict())
service: Optional[ChatService] = None


def chat_key(bot, event):
    if isinstance(event, GroupMessageEvent):
        return f"{bot.self_id}:group:{event.group_id}"
    return f"{bot.self_id}:private:{event.user_id}"


def readable(message):
    parts = []
    for segment in message:
        if segment.type == "text":
            parts.append(str(segment.data.get("text", "")))
        elif segment.type == "at":
            parts.append("[@" + str(segment.data.get("qq", "")) + "]")
        elif segment.type != "reply":
            parts.append("[" + segment.type + "]")
    return "".join(parts)[:config.agent_chat_max_message_chars]


@driver.on_startup
async def start_agent_chat():
    global service
    if not config.agent_chat_enabled:
        logger.info("agent_chat disabled (no DSH connection or chat recording)")
        return
    service = ChatService(config, Store(config.agent_chat_state_path), DshClient(config))
    logger.info("agent_chat enabled for explicitly allowed conversations")


@driver.on_shutdown
async def stop_agent_chat():
    global service
    if service:
        await service.close()
        service = None


@event_preprocessor
async def observe_chat(bot: Bot, event: MessageEvent, state: T_State):
    if not service or not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    if not service.allowed(bot.self_id, group_id, event.user_id):
        return
    reply = event.reply
    quoted_user = str(reply.sender.user_id) if reply and reply.sender.user_id is not None else ""
    directed = isinstance(event, PrivateMessageEvent) or event.is_tome() or quoted_user == str(bot.self_id)
    message = ChatMessage(
        key=chat_key(bot, event), message_id=str(event.message_id), user_id=str(event.user_id),
        name=(getattr(event.sender, "card", None) or event.sender.nickname or str(event.user_id))[:80],
        text=readable(event.message), timestamp=float(event.time), directed=directed,
        reply_to=str(reply.message_id) if reply else "",
        reply_text=readable(reply.message) if reply else "", reply_user_id=quoted_user,
    )
    fresh = service.observe(message)
    # NoneBot shallow-copies state per matcher; this nested bucket is intentionally shared.
    state[CONTEXT_KEY] = {"message": message, "fresh": fresh, "claimed": False,
                          "takeover": bool(fresh and directed and config.agent_chat_takeover_mentions)}


@run_postprocessor
async def note_existing_handler(matcher: Matcher, state: T_State):
    bucket = state.get(CONTEXT_KEY)
    if bucket is not None and not getattr(matcher, "agent_chat_passive", False):
        bucket["claimed"] = True


@event_postprocessor
async def dispatch_chat(bot: Bot, event: MessageEvent, state: T_State):
    bucket = state.get(CONTEXT_KEY)
    if not service or not bucket or not bucket["fresh"] or bucket["claimed"]:
        return
    message = bucket["message"]

    async def send(text):
        # Construct a literal text segment: model-produced CQ code never executes.
        await bot.send(event, Message(MessageSegment.text(text)))

    service.schedule(message, send)


admin = on_command("ai", permission=SUPERUSER, priority=1, block=True)


@admin.handle()
async def administer(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not service:
        await admin.finish("AI 桥接未启用。")
    key = chat_key(bot, event)
    command = args.extract_plain_text().strip()
    if command in {"状态", "status"}:
        bound = service.store.session(key)
        status = "未创建会话" if not bound else ("已暂停，需要检查 DSH 后重置" if bound[2] else "会话已保存")
        await admin.finish("AI 桥接：" + status)
    if command in {"重置", "reset"}:
        try:
            await service.reset(key)
        except Exception:
            await admin.finish("未能确认 DSH 旧任务已停止，保留会话并暂停重置。")
        await admin.finish("当前对话的 AI 映射与本地上下文已重置。DSH 历史仍保留。")
    await admin.finish("用法：ai 状态 / ai 重置（仅机器人超级用户）。")
