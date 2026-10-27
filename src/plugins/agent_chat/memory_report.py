"""Human-readable memory views. No model calls or edits to stored memory contents."""
import re
from .forward_report import ForwardReport, MAX_NODE_CHARS, CHUNKS_PER_PAGE

CATEGORIES={'activeTopic':'最近在聊的事','pendingThought':'想接着聊的事','memberImpression':'对群友的印象'}
ALIASES={'话题':'activeTopic','想法':'pendingThought','群友':'memberImpression',**{k:k for k in CATEGORIES}}
OPTIONS={'activeTopic':'话题','pendingThought':'想法','memberImpression':'群友'}
USAGE='用法：ai 记忆 [话题/想法/群友] [页码]。默认隐藏编号和内部标签；ai 记忆 管理 可查看删除编号。'


def options(tail):
    category='';page=1;manage=False;seen=set()
    for token in tail.split():
        if token in ALIASES and 'category' not in seen:
            category=ALIASES[token];seen.add('category')
        elif token=='管理' and not manage:manage=True
        elif re.fullmatch(r'[1-9][0-9]{0,5}',token) and 'page' not in seen:
            page=int(token);seen.add('page')
        else:raise ValueError('invalid_memory_view_option')
    return category,page,manage


def entry_text(row,manage=False):
    extra=row['extra'];text=row['content']
    if row['category']=='memberImpression':
        text=(extra.get('name') or '未署名群友')+'：'+text
    elif row['category']=='activeTopic':
        if extra.get('participants'):text+='\n参与者：'+'、'.join(extra['participants'])
        if extra.get('pendingQuestion'):text+='\n还没聊完：'+extra['pendingQuestion']
    if manage:text=f"删除编号 {row['id']}\n"+text
    return text


def build_memory_report(store,key,tail):
    try:category,page,manage=options(tail)
    except ValueError:return USAGE
    rows=store.memory(key,category)
    if not rows:return '当前群没有有效轻量记忆。' if ':group:' in key else '当前对话没有有效轻量记忆。'
    chunks=[]
    for kind,label in CATEGORIES.items():
        records=sorted((r for r in rows if r['category']==kind),key=lambda r:(r['updated'],r['id']),reverse=True)
        if not records:continue
        title=label+'\n\n';current=title
        for row in records:
            text=entry_text(row,manage)
            if len(title)+len(text)>MAX_NODE_CHARS:raise ValueError('oversized_memory_record')
            if len(current)+len(text)+2>MAX_NODE_CHARS:
                chunks.append(current.rstrip());current=title
            current+=text+'\n\n'
        if current!=title:chunks.append(current.rstrip())
    pages=max(1,(len(chunks)+CHUNKS_PER_PAGE-1)//CHUNKS_PER_PAGE)
    if page>pages:return f'当前只有 {pages} 页。'+USAGE
    command='ai 记忆'+(' '+OPTIONS[category] if category else '')+(' 管理' if manage else '')
    header=(f'当前对话记忆 · 第{page}/{pages}页\n共{len(rows)}条，按类别整理，每类较新的内容在前。'
            +('\n需要删除时使用 ai 忘记 编号。' if manage else '')
            +(f'\n下一页：{command} {page+1}' if page<pages else ''))
    return ForwardReport(tuple([header]+chunks[(page-1)*CHUNKS_PER_PAGE:page*CHUNKS_PER_PAGE]),page,pages,len(rows),
                         title='当前对话记忆',unit='条记忆',preview='按话题、想法与群友印象整理，点击展开。',command=command)
