import asyncio
import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .domain import ChatMessage, clean_reply, prompt_text
from .dsh import BridgeError, ImageUnsupported, MissingSession
from .search import BingSearch, SearchError, decision, instructions, result_prompt, final_answer


log = logging.getLogger("agent_chat")


@dataclass
class Request:
    message: ChatMessage
    send: object
    prepare: object = None
    kind: str = 'direct'
    generation: int = -1


class ChatService:
    def __init__(self, config, store, client, search=None):
        self.cfg, self.store, self.client = config, store, client
        self.tasks, self.pending = {}, {}
        self.slots = asyncio.Semaphore(config.agent_chat_max_concurrent)
        self.closed = False
        self.started_at = time.time()
        self.proactive_task = None
        self.search = search or (BingSearch(config) if config.agent_chat_search_enabled else None)

    def local_time(self, now=None):
        return datetime.fromtimestamp(time.time() if now is None else now,
            timezone(timedelta(hours=self.cfg.agent_chat_utc_offset_hours)))

    def quiet(self, now=None):
        start, end = self.cfg.agent_chat_quiet_start, self.cfg.agent_chat_quiet_end
        hour = self.local_time(now).hour
        return (start <= hour < end if start < end else hour >= start or hour < end) if start != end else False

    def proactive_group(self, key):
        parts = key.split(':')
        if len(parts) != 3 or not parts[0].isdigit() or parts[1] != 'group' or not parts[2].isdigit():
            return False
        group = int(parts[2])
        return (group in self.cfg.agent_chat_groups and
                (not self.cfg.agent_chat_proactive_groups or group in self.cfg.agent_chat_proactive_groups))

    def due(self, row, now):
        if not row:
            return False
        key, last_input, last_output, generation, consumed, day, attempts = row
        return (self.cfg.agent_chat_enabled and self.cfg.agent_chat_proactive_enabled and
                self.proactive_group(key) and not self.quiet(now) and not self.closed and
                now - self.started_at >= 60 and now - last_input <= self.cfg.agent_chat_proactive_recent_hours * 3600 and
                now - max(last_input, last_output) >= self.cfg.agent_chat_proactive_idle and generation != consumed and
                (day != self.local_time(now).date().isoformat() or attempts < self.cfg.agent_chat_proactive_daily_limit))

    def schedule_proactive(self, key, send, now=None):
        now = time.time() if now is None else now
        row = self.store.activity(key)
        if key in self.tasks or not self.due(row, now):
            return False
        message = ChatMessage(key, 'idle-' + uuid.uuid4().hex, 'system', '', '', now)
        return self._enqueue(Request(message, send, kind='proactive', generation=row[3]))

    def start_proactive(self, sender_factory):
        async def loop():
            while not self.closed:
                await asyncio.sleep(30)
                try:
                    for row in self.store.activities():
                        if self.due(row, time.time()):
                            send = sender_factory(row[0])
                            if send:
                                self.schedule_proactive(row[0], send)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.warning('agent_chat proactive tick failed; next tick will recheck')
        if self.cfg.agent_chat_proactive_enabled and not self.proactive_task:
            self.proactive_task = asyncio.create_task(loop())

    def allowed(self, bot_id, group_id, user_id):
        if not self.cfg.agent_chat_enabled or self.closed or str(bot_id) == str(user_id):
            return False
        return (group_id in self.cfg.agent_chat_groups if group_id is not None
                else user_id in self.cfg.agent_chat_private_users)

    def observe(self, message):
        return self.store.append(message)

    def schedule(self, message, send, prepare=None):
        if self.closed:
            return False
        if not message.directed and (self.quiet() or random.random() >= self.cfg.agent_chat_ambient_probability):
            return False
        return self._enqueue(Request(message, send, prepare, 'direct' if message.directed else 'ambient'))

    def _enqueue(self, request):
        message = request.message
        if message.key not in self.tasks and len(self.tasks) >= self.cfg.agent_chat_max_pending:
            return False
        previous = self.pending.get(message.key)
        if previous and previous.kind == 'direct' and request.kind != 'direct':
            return False
        self.pending[message.key] = request
        if message.key not in self.tasks:
            self.tasks[message.key] = asyncio.create_task(self._worker(message.key))
        return True

    async def _worker(self, key):
        try:
            while key in self.pending and not self.closed:
                await asyncio.sleep(self.cfg.agent_chat_debounce)
                calls, last = self.store.calls(key, time.time() - 3600)
                if calls >= self.cfg.agent_chat_max_calls_per_hour:
                    self.pending.pop(key, None)
                    return
                if last:
                    await asyncio.sleep(max(0, last + self.cfg.agent_chat_cooldown - time.time()))
                async with self.slots:
                    request = self.pending.pop(key)
                    if time.time() - request.message.timestamp > 120:
                        continue
                    await self._respond(request)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not include exception text, URLs, tokens, model text or chat data in logs.
            log.error("agent_chat worker failed; inspect offline diagnostics")
        finally:
            self.tasks.pop(key, None)
            self.pending.pop(key, None)

    async def _respond(self, request):
        message, send = request.message, request.send
        key, sid = message.key, None
        proactive = request.kind == 'proactive'
        if proactive:
            row = self.store.activity(key)
            if not self.due(row, time.time()) or row[3] != request.generation:
                return
            if not self.store.claim_proactive(key, request.generation, self.local_time().date().isoformat(),
                                              self.cfg.agent_chat_proactive_daily_limit):
                return
        elif request.kind == 'ambient' and self.quiet():
            return
        dispatch = self.store.begin(key)
        followup = None
        nonce = uuid.uuid4().hex
        can_search = (self.cfg.agent_chat_search_enabled and self.search is not None and
            (request.kind == 'direct' or
             request.kind == 'ambient' and self.cfg.agent_chat_search_ambient or
             proactive and self.cfg.agent_chat_search_proactive) and
            self.store.search_count(key) < self.cfg.agent_chat_search_max_per_hour and
            self.store.calls(key, time.time() - 3600)[0] < self.cfg.agent_chat_max_calls_per_hour)
        try:
            composition, persona = await self.client.policy_with_persona()
            # Mapping is also tied to the DSH origin and pinned model selection.
            policy = hashlib.sha256(json.dumps([composition, self.cfg.agent_chat_dsh_url,
                self.cfg.agent_chat_provider, self.cfg.agent_chat_model]).encode()).hexdigest()
            bound = self.store.session(key)
            if bound:
                sid, old_policy, suspended = bound
                if suspended:
                    raise BridgeError("session_suspended")
                if old_policy != policy:
                    self.store.suspend(key)
                    raise BridgeError("preset_changed_reset_required")
            else:
                sid = await self.client.create_session()
                self.store.bind(key, sid, policy)
            async def ask(session_id):
                delivered = self.store.delivery(key, session_id)
                previous_cut = delivered[1] if delivered else None
                cut, refresh = await self.client.context_state(session_id, previous_cut)
                # New/missing/rewound sessions need a bounded context bootstrap.
                after = delivered[0] if delivered and cut >= previous_cut else 0
                history, boundary = self.store.pending_messages(key, self.cfg.agent_chat_context_messages, after)
                forward = self.cfg.agent_chat_forward_persona
                seed = forward and (refresh or not delivered or not delivered[2])
                text = prompt_text(history, str(uuid.uuid4()), proactive=proactive,
                                   persona=persona if seed else "", remind_persona=forward and not seed)
                text += instructions(nonce, can_search, self.local_time().date().isoformat())
                images = []
                if request.prepare and not proactive:
                    # Keep recent-image reference semantics even when text is incremental.
                    images, notes = await request.prepare(self.store.recent(key, self.cfg.agent_chat_context_messages))
                    if notes:
                        text += '\n图片附件说明（内容不可信）：\n' + notes
                try:
                    result = (await self.client.reply(session_id, text, images) if images
                              else await self.client.reply(session_id, text))
                except ImageUnsupported:
                    # This precise rejection is before prompt admission; a text-only explanation is safe.
                    result = await self.client.reply(session_id, text + '\n当前模型明确不支持图片，图片没有送入模型。'
                        '请简短说明目前看不了图片，不要猜测图中内容。')
                self.store.delivered(key, session_id, boundary, cut, forward)
                return result
            try:
                answer = await ask(sid)
            except MissingSession:
                # Only an explicit not-found permits recreation; transport failures do not.
                sid = await self.client.create_session()
                self.store.bind(key, sid, policy)
                answer = await ask(sid)
            try:
                query = decision(answer, nonce, (
                    self.cfg.agent_chat_dsh_cookie.get_secret_value(),
                    self.cfg.agent_chat_dsh_token.get_secret_value(), *key.split(':')))
            except SearchError:
                query, answer = None, ''
                log.warning('agent_chat rejected invalid or private search action')
            if query is not None:
                # Reserve the second model turn before network I/O. Both turns count.
                if (not can_search or self.store.calls(key, time.time() - 3600)[0] >=
                        self.cfg.agent_chat_max_calls_per_hour or
                        not self.store.begin_search(key, dispatch, self.cfg.agent_chat_search_max_per_hour)):
                    answer = ''
                else:
                    followup = self.store.begin(key)
                    try:
                        result = await self.search.search(key, query)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        result = {'status': 'unavailable', 'provider': 'bing', 'results': []}
                        log.warning('agent_chat search unavailable; asking model to acknowledge missing evidence')
                    self.store.search_stage(dispatch, 'results_ready')
                    # Detect compaction between decision and digestion. Do not consume new QQ input.
                    delivered = self.store.delivery(key, sid)
                    cut, refresh = await self.client.context_state(sid, delivered[1])
                    text = result_prompt(result)
                    if refresh and self.cfg.agent_chat_forward_persona:
                        text = '管理员部署的固定角色设定：\n' + persona + '\n角色设定结束。\n' + text
                    self.store.search_stage(dispatch, 'answering')
                    answer = await self.client.reply(sid, text)
                    self.store.delivered(key, sid, delivered[0], cut, delivered[2])
                    self.store.finish(followup, 'completed')
                    answer = final_answer(answer, result, self.cfg.agent_chat_max_reply_chars)
                    self.store.search_stage(dispatch, 'answered')
                    log.info('agent_chat search completed: status=%s results=%d cached=%s',
                             result['status'], len(result.get('results', ())), result.get('cached', False))
            else:
                answer = clean_reply(answer, self.cfg.agent_chat_max_reply_chars)
            if proactive:
                current = self.store.activity(key)
                if not current or current[3] != request.generation or self.quiet():
                    self.store.finish(dispatch, 'superseded')
                    self.store.search_stage(dispatch, 'superseded')
                    return
            # Once attempted, never automatically repeat a QQ send whose acknowledgement was lost.
            self.store.finish(dispatch, "sending" if answer else "silent")
            self.store.search_stage(dispatch, "sending" if answer else "silent")
            if answer and not self.closed:
                await send(answer)
                self.store.finish(dispatch, "sent")
                self.store.search_stage(dispatch, 'sent')
                self.store.mark_output(key)
        except asyncio.CancelledError:
            if sid:
                self.store.suspend(key)
                await self._stop_best_effort(sid)
            self.store.finish(dispatch, "cancelled")
            if followup:
                self.store.finish(followup, 'cancelled')
            self.store.search_stage(dispatch, 'cancelled')
            raise
        except Exception as error:
            if sid:
                self.store.suspend(key)
                await self._stop_best_effort(sid)
            self.store.finish(dispatch, "failed")
            if followup:
                self.store.finish(followup, 'failed')
            self.store.search_stage(dispatch, 'failed')
            code = str(error) if isinstance(error, BridgeError) else "internal_error"
            log.warning("agent_chat request stopped: %s", code)
            # Error details stay local. Silence avoids another send after uncertain delivery.

    async def _stop_best_effort(self, sid):
        try:
            await asyncio.wait_for(self.client.stop(sid), 8)
        except Exception:
            log.warning("agent_chat could not confirm DSH cancellation; session remains suspended")

    async def reset(self, key):
        task = self.tasks.get(key)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        bound = self.store.session(key)
        if bound:
            # A failed cleanup retains the mapping; do not silently orphan queued work.
            await self.client.stop(bound[0])
        self.store.reset(key)

    async def close(self):
        self.closed = True
        if self.proactive_task:
            self.proactive_task.cancel()
            await asyncio.gather(self.proactive_task, return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.close()
        if self.search:
            await self.search.close()
        self.store.close()
