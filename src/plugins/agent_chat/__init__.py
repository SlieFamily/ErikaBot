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
from .presentation import segments as output_segments
from .forwards import ForwardResolver, forward_refs
from .knowledge_bridge import install_route
from .knowledge_admin import handle as knowledge_command


driver = get_driver()
config = load_config(driver.config.dict())
service: Optional[ChatService] = None
media_resolver: Optional[MediaResolver] = None

if config.agent_chat_enabled and (config.agent_chat_memory_enabled or config.agent_chat_slang_enabled):
    install_route(driver.server_app,lambda:service.knowledge_hub if service else None)


def chat_key(bot, event):
    if isinstance(event, GroupMessageEvent):
        return f"{bot.self_id}:group:{event.group_id}"
    return f"{bot.self_id}:private:{event.user_id}"


def outgoing_message(value):
    return Message([MessageSegment(row['type'],row['data']) for row in output_segments(value)])


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
        await bot.send_group_msg(group_id=int(group_id), message=outgoing_message(text))
    return send


@driver.on_startup
async def start_agent_chat():
    global service, media_resolver
    if not config.agent_chat_enabled:
        logger.info("agent_chat disabled (no DSH connection or chat recording)")
        return
    service = ChatService(config, Store(config.agent_chat_state_path), DshClient(config))
    service.start_learning()
    if config.agent_chat_images_enabled:
        media_resolver = MediaResolver(config)
    if config.agent_chat_proactive_enabled:
        service.start_proactive(proactive_sender)
    logger.info(f"agent_chat enabled: {len(config.agent_chat_groups)} allowed groups, "
                f"{len(config.agent_chat_private_users)} allowed private users; incremental context enabled; "
                f"AnySearch native search {'enabled' if config.agent_chat_search_enabled else 'disabled'}")


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
    # OneBot's reply preprocessing removes the segment immediately following a
    # quote, even when it mentions THIS bot rather than the quoted image's sender.
    # Inspect only structured original segments, never raw CQ-looking text.
    mentioned = any(s.type == 'at' and str(s.data.get('qq', '')) == str(bot.self_id)
                    for s in event.original_message)
    directed = isinstance(event, PrivateMessageEvent) or event.is_tome() or mentioned or quoted_user == str(bot.self_id)
    message = ChatMessage(
        key=chat_key(bot, event), message_id=str(event.message_id), user_id=str(event.user_id),
        name=(getattr(event.sender, "card", None) or event.sender.nickname or str(event.user_id))[:80],
        text=readable(event.message), timestamp=float(event.time), directed=directed,
        reply_to=str(reply.message_id) if reply else "",
        reply_text=readable(reply.message) if reply else "", reply_user_id=quoted_user,
        media=tuple((image_refs(event.message) + (image_refs(reply.message) if reply else []))[:config.agent_chat_image_count])
              if config.agent_chat_images_enabled else (),
        forwards=tuple(dict.fromkeys(forward_refs(event.message)+(forward_refs(reply.message) if reply else [])))[:2]
                 if config.agent_chat_forwards_enabled else (),
    )
    fresh = service.observe(message)
    # NoneBot shallow-copies state per matcher; this nested bucket is intentionally shared.
    state[CONTEXT_KEY] = {"message": message, "fresh": fresh, "claimed": False, "command":False,
                          "takeover": bool(fresh and directed and config.agent_chat_takeover_mentions)}


@run_postprocessor
async def note_existing_handler(matcher: Matcher, state: T_State):
    bucket = state.get(CONTEXT_KEY)
    if bucket is not None and not getattr(matcher, "agent_chat_passive", False):
        bucket["claimed"] = True
        bucket["command"] = True


@event_postprocessor
async def dispatch_chat(bot: Bot, event: MessageEvent, state: T_State):
    bucket = state.get(CONTEXT_KEY)
    if not service or not bucket or not bucket["fresh"]:
        return
    message = bucket["message"]
    if (config.agent_chat_memory_enabled or config.agent_chat_slang_enabled) and isinstance(event,GroupMessageEvent) and not bucket.get('command'):
        service.learn_message(message,event.message.extract_plain_text())
    if bucket['claimed']:
        return

    async def send(text):
        # Only validated reply/face metadata creates segments; CQ text is never parsed.
        await bot.send(event, outgoing_message(text))

    if media_resolver or config.agent_chat_forwards_enabled:
        async def prepare(history,pending):
            forward_images,forward_notes=(await ForwardResolver(config).prepare(pending,bot.call_api)
                                          if config.agent_chat_forwards_enabled else ([],''))
            images,notes=(await media_resolver.prepare(forward_images+history,bot.call_api)
                          if media_resolver else ([],''))
            return images,'\n'.join(part for part in (forward_notes,notes) if part)
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
    if (isinstance(event,GroupMessageEvent) and event.group_id in config.agent_chat_groups or
            isinstance(event,PrivateMessageEvent) and event.user_id in config.agent_chat_private_users):
        rendered=knowledge_command(service.knowledge,key,command,memory=getattr(service,'memory_manager',None))
        if rendered is not None:
            await admin.finish(Message(MessageSegment.text(rendered)))
    if command in {"状态", "status"}:
        bound = service.store.session(key)
        status = "未创建会话" if not bound else ("已暂停，修复 DSH/API 后可尝试 ai 恢复" if bound[2] else "会话已保存")
        row = service.store.activity(key)
        used = row[6] if row and row[5] == service.local_time().date().isoformat() else 0
        quiet_label = (f'{config.agent_chat_quiet_start}:00—{config.agent_chat_quiet_end}:00'
                       if config.agent_chat_quiet_start != config.agent_chat_quiet_end else '关闭（全天可接话）')
        await admin.finish("AI 桥接：" + status +
            f"\n当前群待处理提问：{service.pending_count(key)} 条；{'有任务处理中或等待调度' if key in service.tasks else '空闲'}。"+
            f"\n近一小时对话回合：{service.store.calls(key, service.local_time().timestamp() - 3600)[0]}/{config.agent_chat_max_calls_per_hour}；排队上限：{config.agent_chat_queue_timeout:g} 秒" +
            f"\nAnySearch 搜索：{'开启' if config.agent_chat_search_enabled else '关闭'}；近一小时搜索回合 {service.store.search_count(key)}/{config.agent_chat_search_max_per_hour}" +
            f"\n读图：{'开启' if config.agent_chat_images_enabled else '关闭'}；随机接话：{config.agent_chat_ambient_probability:.0%}" +
            f"\n主动引用：{'开启' if config.agent_chat_reply_enabled else '关闭'}；QQ表情：{'开启' if config.agent_chat_faces_enabled else '关闭'}；合并转发：{'开启' if config.agent_chat_forwards_enabled else '关闭'}" +
            f"\n自主发言：{'开启' if config.agent_chat_proactive_enabled and service.proactive_group(key) else '关闭'}；今日尝试 {used}/{config.agent_chat_proactive_daily_limit}" +
            f"\n安静时段：{quiet_label}；语音识别暂未启用。"+
            (f"\n轻量记忆：{service.knowledge.status(key)['memory']} 条；共享已确认黑话：{service.knowledge.status(key)['confirmed']} 条；"
             f"后台学习近一小时：{service.knowledge.learning_count()}/{config.agent_chat_learning_max_per_hour}。ai 学习帮助 查看管理命令。"
             if service.knowledge else ''))
    if command in {"恢复", "resume", "recover"}:
        try:
            result = await service.recover(key)
        except BridgeError as error:
            messages = {
                'recovery_busy':'当前仍有请求在处理，请等它结束后再恢复。',
                'recovery_delivery_uncertain':'上次消息是否发送成功无法确认，暂不自动恢复。请先人工核对；ai 重置会改用新会话。',
                'recovery_policy_changed':'预设或模型配置已改变，不能直接恢复旧绑定，请检查配置或使用 ai 重置。',
                'recovery_foreign_input':'检测到非桥接输入，暂不恢复。请检查 DSH 会话，避免同时手动聊天。',
            }
            await admin.finish(messages.get(str(error),'尚未确认 DSH 会话可以安全恢复，保持暂停。请检查 DSH/API 后再试。'))
        except Exception:
            await admin.finish('恢复检查失败，保持原状态，请检查本地日志。')
        await admin.finish({'missing':'当前没有 AI 会话，下次触发时会自动创建。',
            'active':'当前会话未暂停，无需恢复。这不代表聊天 API 已通过健康测试。',
            'resumed':'当前 AI 会话已恢复，保留原有记忆。未重发旧消息，额度不重置；下次新消息触发时继续。'}[result])
    if command in {"重置", "reset"}:
        try:
            await service.reset(key)
        except Exception:
            await admin.finish("未能确认 DSH 旧任务已停止，保留会话并暂停重置。")
        await admin.finish("当前对话的 AI 映射与本地上下文已重置。DSH 历史、独立轻量记忆与共享黑话仍保留；清除记忆请用 ai 清空记忆。")
    await admin.finish("用法：ai 状态 / ai 恢复（保留记忆）/ ai 重置（新会话），仅机器人超级用户。")
