import httpx
import json
import sqlite3
import random
import re
import os

# 获取Bot主目录
path = os.path.abspath(os.getcwd())

def Init():
    '''
    建立语录列表
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    cur.execute('select count(*) from sqlite_master where type="table" and name = "AnaList"')
    if cur.fetchall()[0][0] == 0:
        cur.execute('create table AnaList (ana_name TEXT)') #语录清单
        db.commit()
    cur.execute('select count(*) from sqlite_master where type="table" and name = "ruleList"')
    if cur.fetchall()[0][0] == 0:
        cur.execute('create table ruleList (re_str TEXT)') #高级语录匹配
        db.commit()   
    cur.close()
    db.close()

def AppendList(name:str)->bool:
    '''
    新增语录成员
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'insert into AnaList (ana_name) values ("{name}")')
        db.commit()
        cur.execute(f'create table "_{name}" (ana TEXT UNIQUE, set_by TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)')
        db.commit()
    except:
        return False
    cur.close()
    db.close()

def Isexisted(name:str)->bool:
    '''
    判断语录是否存在于列表
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    cur.execute(f'select * from AnaList where ana_name="{name}"')
    if cur.fetchall() == []:
        cur.close()
        db.close()
        return False
    cur.close()
    db.close()
    return True

def GetAna(name:str,group:str,num:int=-1)->str:
    '''
    通过语录名称和群号随机提取语录
    '''
    ana = ''
    if not Isexisted(name):
        return ana #不存在该语录
    db = sqlite3.connect('db/anas.db')
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
    cur.execute(f'select * from "_{name}"')
    All_anas = cur.fetchall()
    if num == -1:
        try:
            i = random.randint(1,len(All_anas))
            ana = All_anas[i-1][0]
        except:
            pass
    else:
        try:
            ana = All_anas[num-1][0]
        except:
            pass
    cur.close()
    db.close()
    return ana

def IsAdded(name:str,ana:str,by:str)->bool:
    '''
    追加语录
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    if not Isexisted(name):
        AppendList(name)
        if name[-4:-1]+name[-1] == "<高级>":
            UpdateReRule(name[0:-4])
    cur.execute(f'select * from "_{name}" where ana="{ana}"')
    if cur.fetchall() == []:
        try:
            cur.execute(f'insert into "_{name}" values("{ana}","{by}", NULL)')
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
    print(name,ana)
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    if not Isexisted(name):
        return False

    try:
        cur.execute(f'select ana from "_{name}" where ana="{ana}"')
        if cur.fetchall() == []:
            return False #查无此语录
        cur.execute(f'delete from "_{name}" where ana="{ana}"')
        db.commit()
    except:
        print(f"[!]{name}语录删除失败:\n{ana}")
        return False
        
    # 语录为空，全清
    cur.execute(f'select * from "_{name}"')
    All_anas = cur.fetchall()
    if len(All_anas) == 0:
        try:
            cur.execute(f'delete from AnaList where ana_name="{name}"')
            db.commit()
            cur.execute(f'DROP TABLE "_{name}"')
            db.commit()
        except:
            cur.close()
            db.close()
            return False

    if name[-4:-1]+name[-1] == "<高级>":
        CleanReRule(name[:-4])
    ReNumberTab(name)
    cur.close()
    db.close()
    return True

def Merge(name1:str,name2:str)->bool:
    '''
    将语录2 完全迁移到 语录1
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    if not Isexisted(name1) or not Isexisted(name2):
        return False
    cur.execute(f'select * from "_{name2}"')
    n2_anas = cur.fetchall()
    for ana in n2_anas:
        cur.execute(f'insert into "_{name1}" values("{ana[0]}","{ana[1]}", NULL)')
    cur.execute(f'delete from AnaList where ana_name="{name2}"')
    cur.execute(f'DROP TABLE "_{name2}"')
    if name2[-4:-1]+name2[-1] == "<高级>":
        CleanReRule(name2[:-4])
    try:
        db.commit()
        return True
    except:
        db.rollback()
        return False

def SetLock(name:str,group:str)->bool:
    '''
    设置对群限制访问
    '''
    if not Isexisted(name):
        return False
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'update AnaList set group_{group}=1 where ana_name="{name}"')
        db.commit()
    except:
        return False
    return True

def GetList():
    '''
    获取语录清单
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList where ana_name not like "%<高级>%"')
    names = [name[0] for name in cur.fetchall()]
    cnts = []
    for name in names:
        cur.execute(f'select count(*) from "_{name}"')
        cnts.append(cur.fetchall()[0][0])
    return names,cnts

def GetSuperList():
    '''
    获取高级语录清单
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList where ana_name like "%<高级>%"')
    names = [name[0] for name in cur.fetchall()]
    cnts = []
    for name in names:
        cur.execute(f'select count(*) from "_{name}"')
        cnts.append(cur.fetchall()[0][0])
    return names,cnts

def SetUnlock(name:str,group:str)->bool:
    '''
    设置对群限制访问解除
    '''
    if not Isexisted(name):
        return False
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'update AnaList set group_{group}=0 where ana_name="{name}"')
        db.commit()
    except:
        return False
    return True

def GetReRule():
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    cur.execute("select * from ruleList")
    rule = cur.fetchall()
    if not rule:
        return ''
    return rule[0][0]

def UpdateReRule(name:str)->bool:
    '''
    更新 高级语录的规则列表
    '''
    db = sqlite3.connect('db/anas.db')
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

def CleanReRule(name:str)->bool:
    '''
    在高级语录的规则列表中清除指定语录
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    rule = GetReRule()
    if not rule:
        return False
    new_rule = ''
    for k in rule.split(f"|{name}"):
        new_rule += k
    if not new_rule:
        return False
    try:
        cur.execute(f'update ruleList set re_str="{new_rule}" where re_str="{rule}"')
        db.commit()
    except:
        return False
    return True

def Inf(ana:str):
    '''
    获取具体语录(string)的信息
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    names1,cnts1 = GetList()
    names2,cnts2 = GetSuperList()
    names = names1+names2
    inf_list = []
    for name in names:
        cur.execute(f'''select * from "_{name}" where ana like "%{ana}%"''')
        inf = cur.fetchall()
        if inf:
            inf_list.append((name,inf[0][0],inf[0][1],inf[0][2]))
    if inf_list == []:
        return False
    return inf_list

def DropAna(name:str)->bool:
    '''
    删除整个语录
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'delete from AnaList where ana_name="{name}"')
        db.commit()
        cur.execute(f'DROP table "_{name}"')
        db.commit()
        if name[-4:-1]+name[-1] == "<高级>":
            CleanReRule(name[:-4])
        os.system(f"rm -rf imgs/{name}_*")
        return True
    except:
        return False

def RenameAna(name1:str,name2:str)->bool:
    if not Isexisted(name1):
        print(name1,"不存在")
        return False
    if Isexisted(name2):
        print(name2,"存在")
        return False
    if name1 == name2:
        print(name1,name2,"相同")
        return False
    if name1[-4:-1]+name1[-1] == "<高级>":
        CleanReRule(name1[:-4])
    if name2[-4:-1]+name2[-1] == "<高级>":
        UpdateReRule(name2[:-4])
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'update AnaList set ana_name = "{name2}" where ana_name="{name1}"')
        db.commit()
        cur.execute(f'ALTER table "_{name1}" rename to "_{name2}"')
        db.commit()
        return True
    except:
        return False


def ReNumberTab(name:str)->bool:
    '''
    将旧语录表的主键更新

    由于 sqlite3 本身的问题导致主键不会重新排序
    '''
    db = sqlite3.connect('db/anas.db')
    cur = db.cursor()
    try:
        cur.execute(f'create table "new_{name}" (ana TEXT UNIQUE, set_by TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)')
        cur.execute(f'insert into "new_{name}" (ana, set_by) select ana, set_by from "_{name}"')
        cur.execute(f'drop table "_{name}"')
        cur.execute(f'ALTER table "new_{name}" rename to "_{name}"')
        db.commit()
        return True
    except:
        return False       