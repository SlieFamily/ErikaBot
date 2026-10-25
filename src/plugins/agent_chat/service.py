import asyncio
import hashlib
import json
import logging
import random
import time
import uuid

from .domain import clean_reply, prompt_text
from .dsh import BridgeError, MissingSession


log = logging.getLogger("agent_chat")


class ChatService:
    def __init__(self, config, store, client):
        self.cfg, self.store, self.client = config, store, client
        self.tasks, self.pending = {}, {}
        self.slots = asyncio.Semaphore(config.agent_chat_max_concurrent)
        self.closed = False

    def allowed(self, bot_id, group_id, user_id):
        if not self.cfg.agent_chat_enabled or self.closed or str(bot_id) == str(user_id):
            return False
        return (group_id in self.cfg.agent_chat_groups if group_id is not None
                else user_id in self.cfg.agent_chat_private_users)

    def observe(self, message):
        return self.store.append(message)

    def schedule(self, message, send):
        if self.closed:
            return False
        if not message.directed and random.random() >= self.cfg.agent_chat_ambient_probability:
            return False
        if message.key not in self.tasks and len(self.tasks) >= self.cfg.agent_chat_max_pending:
            return False
        self.pending[message.key] = (message, send)
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
                    message, send = self.pending.pop(key)
                    if time.time() - message.timestamp > 120:
                        continue
                    await self._respond(message, send)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not include exception text, URLs, tokens, model text or chat data in logs.
            log.error("agent_chat worker failed; inspect offline diagnostics")
        finally:
            self.tasks.pop(key, None)
            self.pending.pop(key, None)

    async def _respond(self, message, send):
        key, sid = message.key, None
        dispatch = self.store.begin(key)
        try:
            composition = await self.client.policy()
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
            text = prompt_text(self.store.recent(key, self.cfg.agent_chat_context_messages), str(uuid.uuid4()))
            try:
                answer = await self.client.reply(sid, text)
            except MissingSession:
                # Only an explicit not-found permits recreation; transport failures do not.
                sid = await self.client.create_session()
                self.store.bind(key, sid, policy)
                answer = await self.client.reply(sid, text)
            answer = clean_reply(answer, self.cfg.agent_chat_max_reply_chars)
            # Once attempted, never automatically repeat a QQ send whose acknowledgement was lost.
            self.store.finish(dispatch, "sending" if answer else "silent")
            if answer and not self.closed:
                await send(answer)
                self.store.finish(dispatch, "sent")
        except asyncio.CancelledError:
            if sid:
                self.store.suspend(key)
                await self._stop_best_effort(sid)
            self.store.finish(dispatch, "cancelled")
            raise
        except Exception as error:
            if sid:
                self.store.suspend(key)
                await self._stop_best_effort(sid)
            self.store.finish(dispatch, "failed")
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
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.close()
        self.store.close()
