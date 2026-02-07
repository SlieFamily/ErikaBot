import nonebot
import re
from nonebot import on_command,on_regex,on_notice
from nonebot.rule import to_me
from nonebot.typing import T_State
from nonebot.adapters import Bot, Event
from nonebot.params import ArgPlainText, Arg, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment,GroupIncreaseNoticeEvent
from nonebot.permission import SUPERUSER
from nonebot.log import logger
from nonebot import require
import random
import datetime 

require('nonebot_plugin_apscheduler')
from nonebot_plugin_apscheduler import scheduler


global time_task

time_task = []
time_task.append(('2026年高考',datetime.date(2026,6,7)))
time_task.append(('雪糕cheese生日会',datetime.date(2026,3,3)))

groups = ["818353963","757530435", "1053093162", "555973529"]

async def CallDays()->str:
	msg = '小胶布提醒你，你剩下的时间不多了~\n-----------\n'
	today = datetime.date.today()
	for time in time_task:
		msg += '距离['+time[0]+']还有['+str((time[1]-today).days)+'天]\n'
	msg += '-----------'
	return msg

HowManyDays = on_command("倒计时",aliases=set(['考研倒计时','考研时间','考试']), priority=2)
@HowManyDays.handle()
async def handle(bot: Bot, event: Event, state: T_State):
	msg = await CallDays()
	await HowManyDays.finish(Message(msg))

# 请求定时任务对象scheduler   
@scheduler.scheduled_job('cron', 
						hour=8, minute=00, second=0,
						timezone='Asia/Shanghai',
						id='call_days')
async def AutoCallDays():
	msg = await CallDays()
	if not msg:
		return
	msg += '\n本消息自动发送，当前时间为：8:00 AM'
	schedBot = nonebot.get_bot()
	for group in groups:
		await schedBot.call_api('send_msg',**{
                    			'message':msg,
                        		'group_id':group
                				})

@scheduler.scheduled_job('cron',hour=19, minute=00, second=0,
						timezone='Asia/Shanghai',id='call_umiko')
async def CallUmiko():
	# msg = "[CQ:at,qq=2861867116] 该海猫了"
	schedBot = nonebot.get_bot()
	# await schedBot.call_api('send_msg',**{
 #                			'message':msg,
 #                    		'group_id':"757530435"
 #            				})
	# await schedBot.call_api('send_msg',**{
    #             			'message':"[CQ:at,qq=1364374624] 记得给老娘续费！",
    #                 		'group_id':"983806711"
    #         				})

AddDays = on_command("add 倒计时：",priority=2)
@AddDays.handle()
async def handle(bot: Bot, event: Event , args: Message = CommandArg()):
	args = re.findall("([\u4E00-\u9FA5A-Za-z0-9_]+)，(\d{4}-\d{1,2}-\d{1,2})",args)[0]
	name = args[0]
	date = args[1]
	# print(args)
	await AddDays.finish(Message("开发中……"))