from nonebot import on_request
from nonebot.adapters.onebot.v11 import Bot, GroupRequestEvent
from nonebot.log import logger
import csv
import os
from datetime import datetime

# CSV文件路径
CSV_FILE = "db/group_requests.csv"

# 确保data目录存在
os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)

# 初始化CSV文件（如果不存在则创建表头）
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['申请时间', 'QQ号', '昵称', '申请内容', '群号'])

# 监听入群申请事件
group_request = on_request(priority=5)

@group_request.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    """
    记录入群申请信息到CSV
    """
    # 只处理加群请求（不处理邀请入群）
    if event.sub_type != "add":
        return

    # 获取申请信息
    apply_time = datetime.fromtimestamp(event.time).strftime('%Y-%m-%d %H:%M:%S')
    user_id = str(event.user_id)
    group_id = str(event.group_id)
    comment = event.comment if event.comment else "（无）"

    # 尝试获取申请者昵称
    try:
        user_info = await bot.get_stranger_info(user_id=event.user_id)
        nickname = user_info.get('nickname', '未知')
    except:
        nickname = '未知'

    # 追加到CSV
    try:
        with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([apply_time, user_id, nickname, comment, group_id])

        logger.info(f"[入群申请记录] 群:{group_id} | {nickname}({user_id}) | {comment}")
    except Exception as e:
        logger.error(f"[入群申请记录失败] {e}")
