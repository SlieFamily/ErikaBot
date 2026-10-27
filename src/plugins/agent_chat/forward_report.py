"""Shared bounded forward cards, using NoneBot's native OneBot message factories."""
from dataclasses import dataclass

MAX_NODE_CHARS=1800
CHUNKS_PER_PAGE=9

@dataclass(frozen=True)
class ForwardReport:
    nodes: tuple
    page: int
    pages: int
    entries: int
    title: str = '黑话审核汇总'
    unit: str = '个词条'
    preview: str = '按来源群分组，点击展开查看与确认。'
    command: str = 'ai 黑话'


async def send_report(bot,event,report):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent,Message,MessageSegment
    login=await bot.call_api('get_login_info')
    # Keep AnaList/SAA's real identity and native Message encoding. SAA's aggregate
    # sender cannot pass NapCat's card fields: its default news copies every full
    # node into the card, so long reports upload but the oversized card fails.
    nodes=Message([MessageSegment.node_custom(login['user_id'],login['nickname'],
                   Message(MessageSegment.text(text))) for text in report.nodes])
    card=dict(messages=nodes,source=report.title,prompt='['+report.title+']',
              summary=f'查看本页{len(report.nodes)}条记录',
              news=[{'text':f'第{report.page}/{report.pages}页 · 共{report.entries}{report.unit}'},
                    {'text':report.preview}])
    # Only fixed labels/counts enter the preview; full text stays in literal nodes.
    if isinstance(event,GroupMessageEvent):
        return await bot.call_api('send_group_forward_msg',group_id=event.group_id,**card)
    return await bot.call_api('send_private_forward_msg',user_id=event.user_id,**card)
