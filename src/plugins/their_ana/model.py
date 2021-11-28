import httpx
import json
import sqlite3
import random

def Init():
    '''
    建立语录列表
    '''
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    cur.execute('select count(*) from sqlite_master where type="table" and name = "AnaList"')
    if cur.fetchall()[0][0] == 0:
        cur.execute('create table AnaList (ana_name TEXT)')
        cur.execute('create table ruleList (re_str TEXT)')
        db.commit()
    cur.close()
    db.close()

def AppendList(name:str)->bool:
    '''
    新增语录成员
    '''
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'insert into AnaList (ana_name) values ("{name}")')
        db.commit()
        cur.execute(f'create table _{name} (ana TEXT UNIQUE, set_by TEXT)')
        db.commit()
    except:
        return False
    cur.close()
    db.close()

def Isexisted(name:str)->bool:
    '''
    判断语录是否存在于列表
    '''
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    cur.execute(f'select * from AnaList where ana_name="{name}"')
    if cur.fetchall() == []:
        cur.close()
        db.close()
        return False
    cur.close()
    db.close()
    return True

def GetAna(name:str,group:str)->str:
    '''
    通过语录名称和群号随机提取语录
    '''
    ana = ''
    if not Isexisted(name):
        return ana #不存在该语录
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'select * from AnaList where ana_name="{name}" and group_{group}=1')
        if cur.fetchall():
            cur.close()
            db.close()
            return ana #该群限制访问
    except:
        cur.execute(f'alter table AnaList add group_{group} INTEGER default 0')
        db.commit() #为新群创建访问字段
    cur.execute(f'select * from _{name}')
    All_anas = cur.fetchall()
    try:
        i = random.randint(0,len(All_anas))
        ana = All_anas[i-1][0]
    except:
        cur.close()
        db.close()
        return ana
    cur.close()
    db.close()
    return ana

def IsAdded(name:str,ana:str,by:str)->bool:
    '''
    追加语录
    '''
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    if not Isexisted(name):
        AppendList(name)
    cur.execute(f'select * from _{name} where ana="{ana}"')
    if cur.fetchall() == []:
        try:
            cur.execute(f'insert into _{name} values("{ana}","{by}")')
            db.commit()
            cur.close()
            db.close()
            return True
        except:
            cur.close()
            db.close()
            return False
    return False

def IsDel(name:str,ana:str)->bool:
    '''
    删除语录
    '''
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    if not Isexisted(name):
        return False
    try:
        cur.execute(f'select * from _{name} where ana="{ana}"')
        if cur.fetchall() == []:
            return False
        cur.execute(f'delete from _{name} where ana="{ana}"')
        db.commit()
        # 语录为空，全清
        cur.execute(f'select * from _{name}')
        All_anas = cur.fetchall()
        if len(All_anas) == 0:
            cur.execute(f'delete from AnaList where ana_name="{name}"')
            db.commit()
            cur.execute(f'DROP TABLE _{name}')
            db.commit()
    except:
        cur.close()
        db.close()
        return False
    cur.close()
    db.close()
    return True

def Merge(name1:str,name2:str)->bool:
    '''
    将语录2 完全迁移到 语录1
    '''
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    if not Isexisted(name1) or not Isexisted(name2):
        return False
    cur.execute(f'select * from _{name2}')
    n2_anas = cur.fetchall()
    for ana in n2_anas:
        cur.execute(f'insert into _{name1} values{ana}')
    cur.execute(f'delete from AnaList where ana_name="{name2}"')
    cur.execute(f'DROP TABLE _{name2}')
    try:
        db.commit()
        return True
    except:
        db.rollback()
        return False

def SetLock(name:str,group:str)->bool:
    if not Isexisted(name):
        return False
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'update AnaList set group_{group}=1 where ana_name="{name}"')
        db.commit()
    except:
        return False
    return True

def GetList():
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList')
    return cur.fetchall()

def SetUnlock(name:str,group:str)->bool:
    if not Isexisted(name):
        return False
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'update AnaList set group_{group}=0 where ana_name="{name}"')
        db.commit()
    except:
        return False
    return True

def GetReRule():
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    cur.execute("select * from ruleList")
    rule = cur.fetchall()
    if not rule:
        return ''
    return rule[0][0]

def UpdateReRule(name:str)->bool:
    if not Isexisted(name+"迫害"):
        return False
    db = sqlite3.connect('anas.db')
    cur = db.cursor()
    rule = GetReRule()
    if not rule:
        return False
    new_rule = rule+'|'+name
    try:
        cur.execute(f'update ruleList set re_str="{new_rule}" where re_str="{rule}"')
        db.commit()
    except:
        return False
    return True