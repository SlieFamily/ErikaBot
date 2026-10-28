"""Bounded, paged moderation reports; no model calls or raw chat excerpts."""
from .forward_report import ForwardReport as SlangReport, send_report, MAX_NODE_CHARS
import re

# 黑话报告独立的小页预算：不改变记忆报告，不截断词条，也不自动连发后续页。
CHUNKS_PER_PAGE=3          # 每页最多3个来源段，另加1个说明节点
MAX_PAGE_CHARS=2200       # 每页正文字符总数（含来源标题，不含说明节点）
MAX_ENTRIES_PER_PAGE=12   # 每页最多12次词条展示；跨群同词分别计数

SLANG_COMMANDS=frozenset({'黑话','黑话确认','黑话拒绝','黑话删除','黑话添加','黑话帮助','学习帮助','黑话解锁','黑话历史','黑话回退'})
STATUSES={'候选':'candidate','自动':'learned','已确认':'confirmed','已拒绝':'rejected','已锁定':'confirmed'}
LABELS={v:k for k,v in STATUSES.items()}
USAGE=('用法：ai 黑话 [候选/自动/已锁定/已拒绝] [全部] [页码]。\n'
       '默认汇总累计学习至少2次的词；加“全部”包含低频词和手工词条。例如 ai 黑话 候选 全部 2。\n'
       'AI群只展示当前群的来源记录；非AI审核群按来源群汇总，每次只发送一份合并转发。'
       '“全部”只放宽词频，不改变群范围；ai 黑话确认 12 15 18 可跨群批量锁定；ai 黑话解锁 12 恢复自动修订。')

def report_options(tail):
    status=None;minimum=2;page=1;seen=set()
    for token in tail.split():
        if token in STATUSES and 'status' not in seen:
            status=STATUSES[token];seen.add('status')
        elif token=='全部' and 'minimum' not in seen:
            minimum=0;seen.add('minimum')
        elif re.fullmatch(r'[1-9][0-9]{0,5}',token) and 'page' not in seen:
            page=int(token);seen.add('page')
        else:raise ValueError('invalid_report_option')
    return status,minimum,page


def entry_text(row,observed):
    frequency=f"累计学习 {row['count']} 次"+(f"；本群留存来源 {observed} 条" if observed is not None else '')
    lines=[f"#{row['id']} {row['content']} [{LABELS[row['status']]}]",frequency,
           '解释：'+(row['meaning'] or '待自动理解；证据不足时继续积累或研究')]
    for field,label,limit in [('usage','用法',120),('example','例句',120),('risk','注意',300)]:
        if row[field]:lines.append(label+'：'+row[field][:limit]+('…' if len(row[field])>limit else ''))
    if row['sources']:
        links=[u for u in row['sources'] if isinstance(u,str) and len(u)<=220][:2]
        lines.append('公开来源：'+(' '.join(links) if links else '链接较长，已省略')+
                     ('（其余链接省略）' if links and len(links)<len(row['sources']) else ''))
    return '\n'.join(lines)


def build_report(store,bot_id,tail,*,chat_key=None):
    try:status,minimum,page=report_options(tail)
    except ValueError:return USAGE
    rows=[r for r in store.slang_report_rows(bot_id) if r['count']>=minimum and (status is None or r['status']==status)]
    if chat_key is not None:
        if not re.fullmatch(re.escape(str(bot_id))+r':group:[0-9]{1,20}',chat_key):
            raise ValueError('invalid_report_group')
        # Shared definitions keep their ID, but only this group's observed origin
        # is exported. Unattributed manual entries belong to the central report.
        rows=[dict(row,groups=[(key,n) for key,n in row['groups'] if key==chat_key])
              for row in rows if any(key==chat_key for key,_ in row['groups'])]
    if not rows:return '暂无符合条件的黑话。默认只看至少2次的已学习词；可用 ai 黑话 全部 查看低频和手工词条。'
    groups={}
    for row in rows:
        for key,count in row['groups'] or [('manual',None)]:groups.setdefault(key,[]).append((row,count))
    report_pages=[];chunks=[];page_chars=0;page_entries=0
    for key in sorted(groups,key=lambda k:(k=='manual',int(k.rsplit(':',1)[-1]) if k!='manual' else 0)):
        label='共享手工词条（无本机器人来源群记录）' if key=='manual' else '来源群 '+key.rsplit(':',1)[-1]
        values=sorted(groups[key],key=lambda item:(-item[0]['count'],-(item[1] or 0),item[0]['id']))
        part=0;current=None
        for row,observed in values:
            text=entry_text(row,observed)
            new_node=current is None or len(chunks[current])+len(text)+2>MAX_NODE_CHARS
            addition=(f'{label} · 第{part+1}段\n' if new_node else '\n\n')+text
            if chunks and (page_entries>=MAX_ENTRIES_PER_PAGE or
                           page_chars+len(addition)>MAX_PAGE_CHARS or
                           new_node and len(chunks)>=CHUNKS_PER_PAGE):
                report_pages.append(tuple(chunks));chunks=[];page_chars=0;page_entries=0
                new_node=True
                addition=f'{label} · 第{part+1}段\n'+text
            # An entry stays whole; reject corrupt oversized records instead of truncating.
            if new_node:
                if len(addition)>min(MAX_NODE_CHARS,MAX_PAGE_CHARS):raise ValueError('oversized_slang_record')
                part+=1;chunks.append(addition);current=len(chunks)-1
            else:chunks[current]+=addition
            page_chars+=len(addition);page_entries+=1
    if chunks:report_pages.append(tuple(chunks))
    pages=len(report_pages)
    if page>pages:return f'当前只有 {pages} 页。'+USAGE
    options=(' '+LABELS[status] if status else '')+(' 全部' if minimum==0 else '')
    scope='当前群 '+chat_key.rsplit(':',1)[-1] if chat_key else '黑话审核汇总'
    header=(f'{scope} · 第{page}/{pages}页\n共{len(rows)}个词条，{len(groups)}个来源分组；'
            +('包含低频/手工词条。' if minimum==0 else '累计学习至少2次。')+
            '\n按累计学习次数降序；它不是全量聊天词频，本群来源数受留存上限影响。'
            '\n同一词在多个来源群重复展示时共用编号；自动词义可使用且持续修订；确认后锁定。'
            '\n确认：ai 黑话确认 12 15 18；确认即锁定；可用 ai 黑话历史 编号 查看修订、ai 黑话回退 编号 版本 回退并锁定。'
            +(f'\n下一页：ai 黑话{options} {page+1}' if page<pages else '\n已到最后一页。'))
    return SlangReport((header,)+report_pages[page-1],page,pages,len(rows))
