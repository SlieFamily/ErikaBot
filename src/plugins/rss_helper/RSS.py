import sqlite3
from typing import Any, Dict, List, Optional
from nonebot.log import logger
import json
import os

js_path = os.path.dirname(__file__)
js_path = js_path.replace("\\", "/")

'''
TABLE user_list [
                    name(用户名), 
                    user_id(账号), 
                    msg_id(推送信息标识), 
                    url(订阅源),
]

TABLE _username [
                    group_id(订阅群组),
                    translate(是否翻译)
]
'''
def LoadRssRule()->dict:
    with open(js_path+'/config.json','r',encoding = 'utf-8') as fp:
        data =  json.load(fp)
    return data

def Init2db(): 
    '''
    初始化数据库
    ''' 
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute('select count(*) from sqlite_master where type="table" and name = "user_list"')
    if cur.fetchall()[0][0]==0: #不存在则创建表
        cur.execute('create table user_list (name TEXT,user_id TEXT,msg_id TEXT,url TEXT)')
        db.commit()
    cur.close()
    db.close()

def AddUser(app:str, user_id:str, screen_name:str)->bool:
    '''
    创建用户对应的表
    '''
    data = LoadRssRule()
    url = data['rss_url']
    route = data['rss_route'][app]
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select count(*) from user_list where user_id="{user_id}"')
    if cur.fetchall()[0][0]==0:
        if app == '推特':
            url = "https://nitter.x86-64-unknown-linux-gnu.zip/"+user_id+"/with_replies/rss"
        else:
            url = url+route+user_id
        cur.execute(f'insert into user_list values("{screen_name}","{user_id}","","{url}")')
        db.commit()
        cur.execute(f'create table _{user_id} (group_id TEXT,translate TEXT)')
    else:
        logger.warning("用户记录已存在！")
    cur.close()
    db.close()
    
def AddCard(user_id:str, group_id:str)->int: 
    '''
    添加订阅信息 
    返回类型 记录是否已存在(int)1：存在
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select count(*) from _{user_id} where group_id="{group_id}"')
    if cur.fetchall()[0][0] != 0:
        logger.warning('[!]该用户已关注！')
        return 1
    cur.execute(f'insert into _{user_id} values("{group_id}",0)')
    db.commit()
    cur.close()
    db.close()
    return 0
    
def DeleteCard(user_id:str, group_id:str):
    '''
    删除订阅信息 
    返回类型 删除是否成功(int)1:失败 ：成功
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select count(*) from _{user_id} where group_id="{group_id}"')
    if cur.fetchall()[0][0]==0:
        logger.error('[!]记录不存在！删除失败！')
        return 1
    cur.execute(f'delete from _{user_id} where group_id="{group_id}"')
    cur.execute(f'select count(*) from _{user_id}')
    if cur.fetchall()[0][0]==0:
        cur.execute(f'drop table _{user_id}')
        cur.execute(f'delete from user_list where user_id="{user_id}"')
    db.commit()
    cur.close()
    db.close()
    return 0
    
def DeleteGroupCard(group_id:str):
    '''
    删除群聊全部订阅列表
    '''
    users = GetUserList()
    for user in users:
        DeleteCard(user[1],group_id)
        
def GetCard(user_id:str, group_id:str):
    '''
    获取当前群聊的所关注订阅
    '''
    res=[]
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select * from _{user_id} where group_id="{group_id}"')
    data = cur.fetchall()
    if len(data) == 0:
        cur.close()
        db.close()
        return res
    else:
        res = data[0]
        cur.close()
        db.close()
        return res
        
def GetALLCard(user_id:str):
    '''
    获取全部订阅信息
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select * from _{user_id}')
    data = cur.fetchall()
    cur.close()
    db.close()
    return data
    
    
def GetUserList()->List:
    '''
    获取用户列表
    '''
    res = []
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute('select * from user_list')
    data = cur.fetchall()
    if len(data) == 0:
        cur.close()
        db.close()
        return res
    for index in data:
        res.append(index)
    cur.close()
    db.close()
    return res
    
def GetUserInfo(user_id:str)->List:
    '''
    获取用户信息
    '''
    res = []
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select * from user_list where user_id="{user_id}"')
    data = cur.fetchall()
    if len(data) != 0:
        res = data[0]
    cur.close()
    db.close()
    return res
    
def UpdateMsg(user_id:str, msg_id:str):
    '''
    更新用户最新信息（标识）
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'update user_list set msg_id="{msg_id}" where user_id="{user_id}"')
    db.commit()
    cur.close()
    db.close()
    
def Empty()->bool:
    '''
    全局用户列表为空
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute('select count(*) from user_list')
    if cur.fetchall()[0][0]==0:
        cur.close()
        db.close()
        return True
    else:
        cur.close()
        db.close()
        return False

def IsNotInCard(user_id:str, group_id:str)->bool: 
    '''
    根据用户账号和群号判断是否关注
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select * from user_list where user_id="{user_id}"')
    user_inf = cur.fetchall()
    if user_inf == []:
        cur.close()
        db.close()
        return True
    screen_name = user_inf[0][0]
    cur.execute(f'select * from _{user_id} where group_id="{group_id}"')
    data = cur.fetchall()
    if len(data) == 0:
        cur.close()
        db.close()
        return True
    else:
        return False

def GetRssUrl(user_id:str)->str:
    '''
    根据用户账号获取订阅源url
    '''
    db = sqlite3.connect('db/rss.db')
    cur = db.cursor()
    cur.execute(f'select * from user_list where user_id="{user_id}"')
    user_inf = cur.fetchall()
    if user_inf == []:
        cur.close()
        db.close()
        return ''
    url = user_inf[0][3]
    return url

# def SetRssRule(app:str, route:str, url:str = 'https://rss.mcseekeri.top')->bool:
#     '''
#     设置订阅RSS的访问规则
#     '''
#     db = sqlite3.connect('db/rss.db')
#     cur = db.cursor()
#     try:
#         cur.execute(f'update rss_rule set route="{route}" and url="{url}" where app_name="{app}"')
#         db.commit()
#         return True
#     except:
#         cur.close()
#         db.close()
#     return False


# def TranslateON(screen_name:str, ID:str):
#     '''
#     开启推文翻译
#     '''
#     db = sqlite3.connect('db/rss.db')
#     cur = db.cursor()
#     table_name = '_'+screen_name
#     cur.execute(f'update {table_name} set translate=1 where id="{ID}"')
#     db.commit()
#     cur.close()
#     db.close()
    
# def TranslateOFF(screen_name:str, ID:str):
#     '''
#     关闭推文翻译
#     '''
#     db = sqlite3.connect('db/rss.db')
#     cur = db.cursor()
#     table_name = '_'+screen_name
#     cur.execute(f'update {table_name} set translate=0 where id="{ID}"')
#     db.commit()
#     cur.close()
#     db.close()