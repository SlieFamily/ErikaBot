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


class ForwardReportError(RuntimeError):
    """Fixed diagnostic labels only; never retain gateway payloads in logs."""
    def __init__(self,api,error=None):
        self.api=api;self.kind=type(error).__name__ if error else 'MissingReceipt'
        info=getattr(error,'info',None)
        info=info if isinstance(info,dict) else {}
        code=info.get('retcode')
        self.retcode=code if type(code) is int else None
        details=' '.join(value[:2048].lower() for field in ('message','wording')
                         if isinstance(value:=info.get(field),str))
        self.reason=('delivery_unconfirmed' if error is None or
                     'qq returned no message receipt' in details or
                     'message delivery was not confirmed' in details else 'gateway_error')
        super().__init__(self.reason)


def failure_notice(error,command):
    if getattr(error,'reason',None)=='delivery_unconfirmed':
        return '合并转发未确认发送成功：QQ 没有返回送达回执。请先检查群内是否已有卡片，避免重复发送；未展开成多条消息。'
    return '合并转发未确认发送成功；未展开成多条消息。请先核对是否收到，再按需重试 '+command+'。'


async def _request(bot,api,**params):
    try:return await bot.call_api(api,**params)
    except Exception as error:raise ForwardReportError(api,error) from error


async def send_report(bot,event,report):
    from nonebot.adapters.onebot.v11 import GroupMessageEvent,Message,MessageSegment
    login=await _request(bot,'get_login_info')
    # Keep AnaList/SAA's real identity and native Message encoding. SAA's aggregate
    # sender cannot pass custom preview fields supported by NapCat and SnowLuma.
    # Bound the preview independently of the literal, complete report body.
    nodes=Message([MessageSegment.node_custom(login['user_id'],login['nickname'],
                   Message(MessageSegment.text(text))) for text in report.nodes])
    card=dict(messages=nodes,source=report.title,prompt='['+report.title+']',
              summary=f'查看本页{len(report.nodes)}条记录',
              news=[{'text':f'第{report.page}/{report.pages}页 · 共{report.entries}{report.unit}'},
                    {'text':report.preview}])
    # Only fixed labels/counts enter the preview; full text stays in literal nodes.
    if isinstance(event,GroupMessageEvent):
        api='send_group_forward_msg';target={'group_id':event.group_id}
    else:
        api='send_private_forward_msg';target={'user_id':event.user_id}
    result=await _request(bot,api,**target,**card)
    # Resource-upload IDs (and message_id=0) alone do not prove chat delivery.
    receipt=result.get('message_id') if isinstance(result,dict) else None
    if isinstance(receipt,str) and len(receipt)<=20:
        try:receipt=int(receipt)
        except ValueError:pass
    if type(receipt) is not int or receipt==0:raise ForwardReportError(api)
    return result
