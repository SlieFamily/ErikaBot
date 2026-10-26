"""Pure command rendering; callers must enforce NoneBot SUPERUSER and chat allowlist."""
from .knowledge import KnowledgeError, category_value

HELP=('记忆：ai 记忆 [activeTopic/pendingThought/memberImpression]；ai 忘记 编号；ai 清空记忆 [类别]\n'
      '黑话：ai 黑话 [候选/已确认/已拒绝]；ai 黑话确认 编号 [解释]；ai 黑话拒绝 编号；'
      'ai 黑话删除 编号；ai 黑话添加 词语 | 解释\n'
      '确认/添加/修改的解释供所有白名单群共享，不共享原始聊天；ai 重置保留轻量记忆与词库。')


def handle(store,key,command):
    head,_,tail=command.partition(' ')
    tail=tail.strip()
    if head not in {'记忆','忘记','清空记忆','黑话','黑话确认','黑话拒绝','黑话删除','黑话添加','学习帮助'}:
        return None
    if not store:return '轻量记忆与黑话功能未启用。'
    try:
        if head=='学习帮助':return HELP
        if head=='记忆':
            rows=store.memory(key,category_value(tail,optional=True))
            return ('当前群轻量记忆：\n'+'\n'.join(f"#{r['id']} [{r['category']}] {r['extra'].get('name','')} {r['content']}" for r in rows))[:3500] if rows else '当前群没有有效轻量记忆。'
        if head=='忘记':
            return f'已删除当前群 {store.remove_memory_id(key,int(tail))} 条记忆。'
        if head=='清空记忆':
            return f"已清理当前群 {store.clear_memory(key,tail)['removed']} 条记忆；其他群不变。"
        if head=='黑话':
            status={'':'candidate','候选':'candidate','已确认':'confirmed','已拒绝':'rejected'}.get(tail)
            if status is None:return HELP
            rows=store.slang_for_admin(key,status)
            if not rows:return '暂无对应黑话词条。'
            lines=[]
            for r in rows:
                lines.append(f"#{r['id']} {r['content']}（累计 {r['count']} 次）\n解释：{r['meaning'] or '待研究/待填写'}"+
                    (f"\n注意：{r['risk']}" if r['risk'] else '')+
                    ('\n来源：'+' '.join(r['sources']) if r['sources'] else ''))
            return ('黑话'+(tail or '候选')+'（研究草稿须管理员确认；已确认解释全群共享）：\n'+'\n\n'.join(lines))[:3500]
        if head=='黑话添加':
            term,sep,meaning=tail.partition('|')
            if not sep:return HELP
            term=store.add_manual_slang(term.strip(),meaning.strip())
            return f'已添加/修改共享黑话「{term}」，状态：已确认。'
        raw_id,_,meaning=tail.partition(' ')
        action={'黑话确认':'confirm','黑话拒绝':'reject','黑话删除':'delete'}[head]
        term=store.review_slang(key,int(raw_id),action,meaning.strip() or None)
        return f'已处理「{term}」。确认后的解释供所有白名单群共享。'
    except (KnowledgeError,ValueError):
        return '操作未完成：请核对编号、类别、解释长度和词条所属群。确认候选前需有解释；输入 ai 学习帮助 查看用法。'
