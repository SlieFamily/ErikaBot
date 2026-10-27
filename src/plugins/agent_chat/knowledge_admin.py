"""Pure command rendering; callers enforce SUPERUSER; only slang moderation may bypass the chat allowlist."""
import re
from .knowledge import KnowledgeError, category_value
from .slang_report import build_report, USAGE
from .memory_report import build_memory_report

HELP=('记忆开关：ai 记忆状态；ai 即时记忆 开/关；ai 后台记忆 开/关；ai 记忆开关 开/关（总开关）；加 全群 可统一设置。\n'
      '记忆：ai 记忆 [话题/想法/群友] [页码]（合并转发）；ai 记忆 管理 查看删除编号；ai 忘记 编号；ai 清空记忆 [类别]\n'
      '黑话：ai 黑话 [候选/自动/已锁定/已拒绝] [全部] [页码]（按来源群合并转发，默认至少2次）；ai 黑话确认 编号 [解释]；批量：ai 黑话确认 1 2 3（使用各自已有解释）；ai 黑话拒绝 编号；'
      'ai 黑话删除 编号；ai 黑话添加 词语 | 解释\n'
      '多行自填：ai 黑话确认 后换行，每行 编号 | 解释；每次最多30条，逐条返回结果。\n'
      '超级用户可在任意群汇总、确认/拒绝/删除黑话，不会为该群开启AI；词条编号跨群唯一。\n'
      '自动词义直接使用并随证据修订；确认/添加即锁定。ai 黑话解锁 编号；ai 黑话历史 编号；ai 黑话回退 编号 版本。\n'
      '词义共享、原聊天不共享；ai 重置保留轻量记忆与词库。')



def confirmation_entries(tail):
    """Accept explicit ID lists or per-line meanings, preserving legacy single edits."""
    if '|' in tail:
        rows=[]
        for line in tail.splitlines():
            if not line.strip():continue
            raw_id,sep,meaning=line.partition('|')
            if not sep or not meaning.strip():raise ValueError('invalid_confirmation_line')
            rows.append((raw_id.strip(),meaning.strip()))
    elif re.fullmatch(r'#?\d{1,18}(?:[\s,，、]+#?\d{1,18})*',tail):
        rows=[(value,None) for value in re.split(r'[\s,，、]+',tail)]
    else:
        fields=tail.split(None,1)
        rows=[(fields[0],fields[1] if len(fields)==2 else None)] if fields else []
    if not 1<=len(rows)<=30:raise ValueError('confirmation_limit')
    result={}
    for raw_id,meaning in rows:
        if not re.fullmatch(r'#?[1-9]\d{0,17}',raw_id):raise ValueError('invalid_confirmation_id')
        entry_id=int(raw_id.lstrip('#'))
        if entry_id in result and result[entry_id]!=meaning:raise ValueError('conflicting_confirmation')
        result[entry_id]=meaning
    return list(result.items())


def confirm_many(store,key,tail,admin_bot=None):
    entries=confirmation_entries(tail)  # Validate syntax before changing any row.
    confirmed,failed=[],[]
    for entry_id,meaning in entries:
        try:
            term=store.review_slang(key,entry_id,'confirm',meaning,admin_bot=admin_bot)
            confirmed.append(f'#{entry_id}「{term}」')
        except KnowledgeError as error:
            reason={'slang_not_visible_here':('编号不存在或不属于当前机器人收集的词条' if admin_bot is not None else '编号不存在或不属于当前群'),
                    'slang_meaning_required':'缺少解释，请先填写或等待研究'}.get(str(error),'解释不符合要求')
            failed.append(f'#{entry_id}：{reason}')
    parts=[f'已确认 {len(confirmed)} 条'+('：'+'、'.join(confirmed) if confirmed else '。')]
    if failed:parts.append('未确认：\n'+'\n'.join(failed))
    if confirmed:parts.append('确认后的各自解释已锁定，AI不再覆盖；可用 ai 黑话解锁 编号 恢复学习。')
    return '\n'.join(parts)


def handle(store,key,command,memory=None,admin_bot=None):
    parts=command.split(None,1)
    head=parts[0] if parts else ''
    tail=parts[1].strip() if len(parts)==2 else ''
    if head not in {'记忆','忘记','清空记忆','黑话','黑话确认','黑话拒绝','黑话删除','黑话添加','学习帮助','记忆状态','即时记忆','后台记忆','记忆开关','黑话帮助','黑话解锁','黑话历史','黑话回退'}:
        return None
    if not store:return '轻量记忆与黑话功能未启用。'
    try:
        if head=='学习帮助':return HELP
        if head=='黑话帮助':return USAGE
        if head in {'记忆状态','即时记忆','后台记忆','记忆开关','黑话帮助'}:
            if not memory:return '记忆控制未启用。'
            if head=='记忆状态':return memory.describe(key)
            args=tail.split();glob=any(a in ('全群','全局') for a in args)
            values=[a for a in args if a not in ('全群','全局')]
            if len(values)!=1 or values[0] not in ('开','关','开启','关闭'):return HELP
            if not memory.cfg.agent_chat_memory_enabled:return '部署配置尚未启用记忆功能，请先设置 AGENT_CHAT_MEMORY_ENABLED。'
            on=values[0] in ('开','开启');mode={'即时记忆':'immediate','后台记忆':'background','记忆开关':'enabled'}[head]
            memory.set('*' if glob else key,mode,on)
            note='；保留已存记忆，清除待整理消息，进行中的旧整理结果会丢弃' if not on and mode in ('enabled','background') else ''
            return ('所有群' if glob else '本群')+head+'已'+('开启' if on else '关闭')+note+'。无需重启。'
        if head=='记忆':return build_memory_report(store,key,tail)
        if head=='忘记':
            entry_id=int(tail)
            if memory:memory.invalidate(key)
            return f'已删除当前群 {store.remove_memory_id(key,int(tail))} 条记忆。'
        if head=='清空记忆':
            category_value(tail,optional=True)
            if memory:memory.invalidate(key)
            return f"已清理当前群 {store.clear_memory(key,tail)['removed']} 条记忆；其他群不变。"
        if head=='黑话':return build_report(store,admin_bot or key.split(':',1)[0],tail)
        if head=='黑话添加':
            term,sep,meaning=tail.partition('|')
            if not sep:return HELP
            term=store.add_manual_slang(term.strip(),meaning.strip())
            return f'已添加/修改共享黑话「{term}」，状态：已确认（锁定，AI不再覆盖）。'
        if head=='黑话确认':return confirm_many(store,key,tail,admin_bot)
        if head=='黑话解锁':
            entries=confirmation_entries(tail)
            if any(meaning is not None for _,meaning in entries):return HELP
            done=[]
            for entry_id,_ in entries:
                store.review_slang(key,entry_id,'unlock',admin_bot=admin_bot);done.append(str(entry_id))
            return '已解锁：'+' '.join(done)+'；AI可根据新证据修订。'
        if head=='黑话历史':
            entry_id=int(tail);rows=store.slang_versions(entry_id,admin_bot or key.split(':')[0])
            return ('当前版本：'+str(store.slang_revision(entry_id))+'\n历史（最多20版）：\n'+'\n'.join(f"v{r['revision']} [{r['status']}] {r['meaning']}" for r in rows))[:3500]
        if head=='黑话回退':
            entry_id,revision=map(int,tail.split())
            store.rollback_slang(entry_id,revision,admin_bot or key.split(':')[0])
            return '已回退并锁定；AI不再覆盖这份解释。'
        raw_id,_,meaning=tail.partition(' ')
        action={'黑话拒绝':'reject','黑话删除':'delete'}[head]
        term=store.review_slang(key,int(raw_id),action,meaning.strip() or None,admin_bot=admin_bot)
        return f'已处理「{term}」。确认后的解释供所有白名单群共享。'
    except (KnowledgeError,ValueError):
        return '操作未完成：请核对编号、类别、解释长度和词条所属群。确认候选前需有解释；批量可用 1 2 3 或每行 编号 | 解释（最多30条）；输入 ai 学习帮助 查看用法。'
