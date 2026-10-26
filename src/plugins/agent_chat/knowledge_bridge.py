"""Loopback-only native-tool RPC. The host, never model arguments, owns chat scope."""
import contextlib
import hashlib
import hmac
import ipaddress
import json
import re
import time
from dataclasses import dataclass

from .knowledge import KnowledgeError, MEMORY_TOOLS, SLANG_TOOLS, TOOLS, CATEGORIES


@dataclass
class KnowledgeScope:
    hub: object
    key: str
    members: dict
    messages: list
    tools: tuple
    memory_revision: object = None
    memory_writes: int = 0


class KnowledgeHub:
    def __init__(self, store, token, memory=None):
        self.store, self.token, self.leases = store, token, {}
        self.memory = memory

    def scope(self, key, messages, memory=True, slang=True):
        members = {str(m['user_id']): str(m['name']) for m in messages if m.get('user_id') and m.get('name')}
        scope = KnowledgeScope(self, key, members, messages,
                              (MEMORY_TOOLS if memory else ()) + (SLANG_TOOLS if slang else ()))
        if self.memory:
            scope.memory_revision=self.memory.settings(key)['revision']
            scope.tools=tuple(t for t in scope.tools if t not in MEMORY_TOOLS or self.memory.allows(scope,t))
        return scope

    @contextlib.contextmanager
    def lease(self, scope, sid, rid):
        identity = (sid, rid)
        if identity in self.leases or len(self.leases) >= 16:
            raise KnowledgeError('knowledge_lease_conflict')
        self.leases[identity] = {'scope': scope, 'expires': time.monotonic()+305, 'calls': {}}
        try:
            yield
        finally:
            self.leases.pop(identity, None)

    def handle(self, body):
        if not isinstance(body, dict) or set(body) != {'session_id','rpc_id','call_id','name','args'}:
            raise KnowledgeError('invalid_request_shape')
        sid, rid, cid, name, args = (body[k] for k in ('session_id','rpc_id','call_id','name','args'))
        if any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',v) for v in (sid,rid,cid)):
            raise KnowledgeError('invalid_request_id')
        lease = self.leases.get((sid,rid))
        if not lease or lease['expires'] < time.monotonic():
            raise KnowledgeError('inactive_bridge_turn')
        scope = lease['scope']
        if name not in scope.tools or name not in TOOLS or not isinstance(args,dict):
            raise KnowledgeError('tool_not_authorized')
        if name in MEMORY_TOOLS and self.memory and not self.memory.allows(scope,name):
            raise KnowledgeError('memory_disabled_or_changed')
        digest = hashlib.sha256(json.dumps([name,args],sort_keys=True).encode()).hexdigest()
        if cid in lease['calls']:
            old_digest, result = lease['calls'][cid]
            if old_digest != digest:
                raise KnowledgeError('call_id_reused')
            return result
        if len(lease['calls']) >= 6:
            raise KnowledgeError('knowledge_turn_limit')
        # Reserve errors too; a model cannot get unlimited attempts at guessing parameters.
        result = {'ok':False,'error':'invalid_arguments'}
        lease['calls'][cid] = (digest,result)
        try:
            result = self.execute(scope,name,args)
        except (KnowledgeError, TypeError, ValueError) as error:
            result = {'ok':False,'error':str(error) if isinstance(error,KnowledgeError) else 'invalid_arguments'}
        lease['calls'][cid] = (digest,result)
        return result

    def execute(self, scope, name, args):
        allowed = {
            'qq_memory_append': {'category','content','extra'}, 'qq_memory_query': {'category'},
            'qq_memory_remove': {'category','content','target'}, 'qq_memory_clear': {'category'},
            'qq_slang_query': {'q'}, 'qq_slang_submit': {'content','context'},
        }
        if set(args) - allowed[name]:
            raise KnowledgeError('unexpected_argument')
        s, key = self.store, scope.key
        if name == 'qq_memory_append':
            extra=args.get('extra')
            if args.get('category')=='memberImpression' and (not isinstance(extra,dict) or not extra.get('target')):
                return {'ok':False,'error':'member_target_required',
                        'hint':'memberImpression 必须在 extra.target 填写群友 user_id，例如 extra={"target":"7"}；其他参数不能代替 target。',
                        'observed_members':dict(list(scope.members.items())[-10:])}
            result=s.append_memory(key,args.get('category'),args.get('content'),args.get('extra'),scope.members)
            if result.get('ok'):scope.memory_writes+=1
            return result
        if name == 'qq_memory_query':
            entries=s.memory(key,args.get('category',''))
            visible=[]
            for category in CATEGORIES:visible.extend([e for e in entries if e['category']==category][-10:])
            return {'ok':True,'untrusted':True,'memory':visible}
        if name == 'qq_memory_remove':
            return s.remove_memory(key,args.get('category'),args.get('content',''),args.get('target',''))
        if name == 'qq_memory_clear':
            return s.clear_memory(key,args.get('category',''))
        if name == 'qq_slang_query':
            return {'ok':True,'untrusted':True,'slang':s.confirmed_slang(args.get('q',''),10)}
        # Model's "context" is never accepted as evidence. Use only current chat's actual messages.
        return s.submit_slang(key,args.get('content'),scope.messages,from_model=True)


def install_route(app, get_hub):
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def endpoint(request: Request):
        hub = get_hub()
        try:
            local = bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
        except ValueError:
            local = False
        supplied = request.headers.get('authorization','')
        if (not local or not hub or not hub.token or
                not hmac.compare_digest(supplied.encode(),('Bearer '+hub.token).encode())):
            return JSONResponse({'ok':False,'error':'unauthorized'},status_code=403)
        data = bytearray()
        try:
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>8192:
                    return JSONResponse({'ok':False,'error':'request_too_large'},status_code=413)
            result = hub.handle(json.loads(data))
        except (ValueError, RecursionError) as error:
            result = {'ok':False,'error':str(error) if isinstance(error,KnowledgeError) else 'invalid_json'}
        return JSONResponse(result,headers={'Cache-Control':'no-store'})

    app.add_route('/agent-chat/knowledge',endpoint,methods=['POST'])
