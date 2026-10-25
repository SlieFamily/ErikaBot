"""ErikaBot ↔ DSH bridge. Disabled unless explicitly configured by the owner."""
from typing import Optional

from nonebot import get_bots, get_driver, on_command
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
from .media import MediaResolver, allowed_url, safe_file_ref


driver = get_driver()
config = load_config(driver.config.dict())
service: Optional[ChatService] = None
media_resolver: Optional[MediaResolver] = None


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


def image_refs(message):
    refs = []
    for segment in message:
        if segment.type != 'image' or len(refs) >= config.agent_chat_image_count:
            continue
        file = segment.data.get('file', '')
        url = segment.data.get('url', '')
        try:
            allowed_url(url)
        except Exception:
            url = ''
        file = file if safe_file_ref(file) else ''
        if file or url:
            refs.append({'file': file, 'url': url})
    return refs


def proactive_sender(key):
    if not service or not service.proactive_group(key):
        return None
    bot_id, _, group_id = key.split(':')
    if bot_id not in get_bots():
        return None

    async def send(text):
        bot = get_bots().get(bot_id)
        if not bot or not service or service.closed or not service.proactive_group(key):
            raise RuntimeError('proactive_target_unavailable')
        await bot.send_group_msg(group_id=int(group_id), message=Message(MessageSegment.text(text)))
    return send


@driver.on_startup
async def start_agent_chat():
    global service, media_resolver
    if not config.agent_chat_enabled:
        logger.info("agent_chat disabled (no DSH connection or chat recording)")
        return
    service = ChatService(config, Store(config.agent_chat_state_path), DshClient(config))
    if config.agent_chat_images_enabled:
        media_resolver = MediaResolver(config)
    if config.agent_chat_proactive_enabled:
        service.start_proactive(proactive_sender)
    logger.info(f"agent_chat enabled: {len(config.agent_chat_groups)} allowed groups, "
                f"{len(config.agent_chat_private_users)} allowed private users; incremental context enabled")


@driver.on_shutdown
async def stop_agent_chat():
    global service, media_resolver
    if service:
        await service.close()
        service = None
    if media_resolver:
        await media_resolver.close()
        media_resolver = None


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
        media=tuple((image_refs(event.message) + (image_refs(reply.message) if reply else []))[:config.agent_chat_image_count])
              if config.agent_chat_images_enabled else (),
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

    if media_resolver:
        async def prepare(history):
            return await media_resolver.prepare(history, bot.call_api)
        service.schedule(message, send, prepare)
    else:
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
        row = service.store.activity(key)
        used = row[6] if row and row[5] == service.local_time().date().isoformat() else 0
        await admin.finish("AI 桥接：" + status +
            f"\n读图：{'开启' if config.agent_chat_images_enabled else '关闭'}；随机接话：{config.agent_chat_ambient_probability:.0%}" +
            f"\n自主发言：{'开启' if config.agent_chat_proactive_enabled and service.proactive_group(key) else '关闭'}；今日尝试 {used}/{config.agent_chat_proactive_daily_limit}" +
            f"\n安静时段：{config.agent_chat_quiet_start}:00—{config.agent_chat_quiet_end}:00；语音识别暂未启用。")
    if command in {"重置", "reset"}:
        try:
            await service.reset(key)
        except Exception:
            await admin.finish("未能确认 DSH 旧任务已停止，保留会话并暂停重置。")
        await admin.finish("当前对话的 AI 映射与本地上下文已重置。DSH 历史仍保留。")
    await admin.finish("用法：ai 状态 / ai 重置（仅机器人超级用户）。")
