"""Bounded, paged moderation reports; no model calls or raw chat excerpts."""
from dataclasses import dataclass
import re

SLANG_COMMANDS=frozenset({'黑话','黑话确认','黑话拒绝','黑话删除','黑话添加','黑话帮助','学习帮助'})
STATUSES={'候选':'candidate','已确认':'confirmed','已拒绝':'rejected'}
LABELS={v:k for k,v in STATUSES.items()}
MAX_NODE_CHARS=1800
CHUNKS_PER_PAGE=9
USAGE=('用法：ai 黑话 [候选/已确认/已拒绝] [全部] [页码]。\n'
       '默认汇总累计学习至少2次的词；加“全部”包含低频词和手工词条。例如 ai 黑话 候选 全部 2。\n'
       '按来源群分组，每次只发送一份合并转发；ai 黑话确认 12 15 18 可跨群批量确认。')

@dataclass(frozen=True)
class SlangReport:
    nodes: tuple
    page: int
    pages: int
    entries: int


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
           '解释：'+(row['meaning'] or '待研究/待填写；填写解释后才能确认')]
    for field,label,limit in [('usage','用法',120),('example','例句',120),('risk','注意',300)]:
        if row[field]:lines.append(label+'：'+row[field][:limit]+('…' if len(row[field])>limit else ''))
    if row['sources']:
        links=[u for u in row['sources'] if isinstance(u,str) and len(u)<=220][:2]
        lines.append('公开来源：'+(' '.join(links) if links else '链接较长，已省略')+
                     ('（其余链接省略）' if links and len(links)<len(row['sources']) else ''))
    return '\n'.join(lines)


def build_report(store,bot_id,tail):
    try:status,minimum,page=report_options(tail)
    except ValueError:return USAGE
    rows=[r for r in store.slang_report_rows(bot_id) if r['count']>=minimum and (status is None or r['status']==status)]
    if not rows:return '暂无符合条件的黑话。默认只看至少2次的已学习词；可用 ai 黑话 全部 查看低频和手工词条。'
    groups={}
    for row in rows:
        for key,count in row['groups'] or [('manual',None)]:groups.setdefault(key,[]).append((row,count))
    chunks=[]
    for key in sorted(groups,key=lambda k:(k=='manual',int(k.rsplit(':',1)[-1]) if k!='manual' else 0)):
        label='共享手工词条（无本机器人来源群记录）' if key=='manual' else '来源群 '+key.rsplit(':',1)[-1]
        values=sorted(groups[key],key=lambda item:(-item[0]['count'],-(item[1] or 0),item[0]['id']))
        part=1;current=f'{label} · 第{part}段\n'
        for row,observed in values:
            text=entry_text(row,observed)
            if len(current)+len(text)+2>MAX_NODE_CHARS:
                chunks.append(current.rstrip());part+=1;current=f'{label} · 第{part}段\n'
            # Storage bounds and field limits keep each complete entry inside one node.
            if len(text)+len(current)>MAX_NODE_CHARS:raise ValueError('oversized_slang_record')
            current+=text+'\n\n'
        if current.strip():chunks.append(current.rstrip())
    pages=max(1,(len(chunks)+CHUNKS_PER_PAGE-1)//CHUNKS_PER_PAGE)
    if page>pages:return f'当前只有 {pages} 页。'+USAGE
    options=(' '+LABELS[status] if status else '')+(' 全部' if minimum==0 else '')
    header=(f'黑话审核汇总 · 第{page}/{pages}页\n共{len(rows)}个词条，{len(groups)}个来源分组；'
            +('包含低频/手工词条。' if minimum==0 else '累计学习至少2次。')+
            '\n按累计学习次数降序；它不是全量聊天词频，本群来源数受留存上限影响。'
            '\n同一词在多个来源群重复展示时共用编号；确认后词义全群共享。'
            '\n确认：ai 黑话确认 12 15 18；无解释需用 编号 解释 补写。'
            +(f'\n下一页：ai 黑话{options} {page+1}' if page<pages else '\n已到最后一页。'))
    return SlangReport(tuple([header]+chunks[(page-1)*CHUNKS_PER_PAGE:page*CHUNKS_PER_PAGE]),page,pages,len(rows))


async def send_report(bot,event,report):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent,Message,MessageSegment
    login=await bot.call_api('get_login_info')
    # Keep AnaList/SAA's real identity and native Message encoding. SAA's aggregate
    # sender cannot pass NapCat's card fields: its default news copies every full
    # node into the card, so long reports upload but the oversized card fails.
    nodes=Message([MessageSegment.node_custom(login['user_id'],login['nickname'],
                   Message(MessageSegment.text(text))) for text in report.nodes])
    card=dict(messages=nodes,source='黑话审核汇总',prompt='[黑话审核汇总]',
              summary=f'查看本页{len(report.nodes)}条记录',
              news=[{'text':f'第{report.page}/{report.pages}页 · 共{report.entries}个词条'},
                    {'text':'按来源群分组，点击展开查看与确认。'}])
    # Only fixed labels/counts enter the preview; full text stays in literal nodes.
    if isinstance(event,GroupMessageEvent):
        return await bot.call_api('send_group_forward_msg',group_id=event.group_id,**card)
    return await bot.call_api('send_private_forward_msg',user_id=event.user_id,**card)
