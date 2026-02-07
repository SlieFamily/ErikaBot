
import sqlite3
import os
import xlrd
import re
from QImage import *

# 获取Bot主目录
path = os.path.abspath(os.getcwd())

def transf_anas_image():
    '''
    批量清理旧版本中的图片问题
    '''
    db = sqlite3.connect(path+'/db/anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList') #获取语录清单
    names = [name[0] for name in cur.fetchall()]

    for name in names: #对每一个语录进行处理
        cur.execute(f'select ana from "_{name}"')
        anas = cur.fetchall()
        print(f"======处理{name}语录=======")
        for ana in anas:
            print("-----START-------")
            ana = ana[0]
            url = get_image_url(ana)
            if url:
                print('获得图片url：',url)
                new_url = image_download(url,name) #下载图片到本地
                if new_url:
                    print('下载图片：',new_url)
                    new_url = 'file://'+path+'/imgs/'+new_url
                    print('更换图片存储位置：',new_url)
                    new_ana = cq_image_to(ana,new_url) #转换CQ格式
                    if new_ana: 
                        print('重建语录内容：',new_ana)
                        cur.execute(f'update "_{name}" set ana = "{new_ana}" where ana = "{ana}"')
                        db.commit()
                    else:
                        print("[!]语录修改失败")
                else:
                    print("[!]图片下载失败")
                    cur.execute(f'delete from "_{name}" where ana="{ana}"')
                    db.commit()
                    print("[!]已将该语录删除")
            else:
                print('[!]当前语录无图片信息')
            print("------END-------")
        print("====================")


def load_anas_byExcel():
    '''
    从其他数据库中批量载入语录至ErikaBot的数据库中
    [ID, TYPE, CONTENT, CREATE_USER, CREATE_TIME, TAG, GROUP_ID]
    '''
    import sys
    sys.path.append("src/plugins/their_ana")
    import model

    file = path+'/db/data.xls'
    df = xlrd.open_workbook(file)
    data = df.sheet_by_name('Result 6')
    print(data.row_values(0))
    for x in range(1,data.nrows):
        ana_inf = data.row_values(x)
        if ana_inf[1] == '1' and ana_inf[5] != '哼<高级>语录' and ('.jpg' not in ana_inf[5]) and ana_inf[5] != '语录':
            if model.IsAdded(ana_inf[5][:-2], ana_inf[2], ana_inf[3]):
                pass
            else:
                print(f'[!]语录添加失败，可能有重复：{ana_inf[5]}:{ana_inf[2]}')

        

def transf_anas_image2():
    '''
    批量清理迁移数据库中的图片问题
    '''
    db = sqlite3.connect(path+'/db/anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList') #获取语录清单


    import sys
    sys.path.append("src/plugins/their_ana")
    import model

    names = [name[0] for name in cur.fetchall()]
    url = 'file://'+path+'/imgs/'
    for name in names: #对每一个语录进行处理
        cur.execute(f'select * from "_{name}"')
        anas = cur.fetchall()
        print(f"======处理{name}语录=======")
        for ana in anas:
            print("-----START-------")
            by = ana[1]
            ana = ana[0]
            if "file:{quotation_path}" in ana:
                print('[!]存在图片迁移问题，删除该语录')
                if not model.IsDel(name, ana):
                    print('[!]语录删除失败')
                else:
                    img = re.findall("(file:{quotation_path}|file:{quotation_path}/)([0-9,a-z,A-Z]+\.image)",ana)
                    mv = os.system(f'mv imgs/{img[0][1]} imgs/{name+"_"+img[0][1]}')
                    if mv != 0:
                        print('[!]图片重命名失败')
                    ana = re.sub("file:{quotation_path}[0-9,a-z,A-Z]+\.image",url+name+"_"+img[0][1],ana)
                    print('[!]修复后如下：',ana)
                    if not model.IsAdded(name, ana, by):
                        print('[!]语录修复失败')
            print("------END-------")
        print("====================")


def add_primary_key():
    '''
    为旧版语录数据库的表新增主键

    由于 sqlite3 本身的问题导致不能在已有表中增加主键，因此需要复制表
    '''
    db = sqlite3.connect(path+'/db/anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList') #获取语录清单

    names = [name[0] for name in cur.fetchall()]
    for name in names: #对每一个语录进行处理

        try:
            cur.execute(f'select id from "_{name}"')
            pass
        except:
            print(f"======处理{name}语录=======")

            cur.execute(f'create table "new_{name}" (ana TEXT UNIQUE, set_by TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)')
            db.commit()

            cur.execute(f'insert into "new_{name}" (ana, set_by) select ana, set_by from "_{name}"')
            db.commit()

            print(f"[!]复制 表{name} 完成！")
            
            cur.execute(f'drop table "_{name}"')
            db.commit()

            cur.execute(f'ALTER table "new_{name}" rename to "_{name}"')

            print(f"[!]恢复 表{name} 完成！")


def updateRss():
    '''
    批量更新推特RSS的订阅源

    临时处理推特RSS无效问题
    '''
    db = sqlite3.connect(path+'/db/rss.db')
    cur = db.cursor()
    cur.execute('select * from user_list where url like "%nitter%"')
    data = cur.fetchall()
    ids = [user[1] for user in data]
    for id in ids:
        print('[!]正在处理用户：',id)
        cur.execute(f'update user_list set url="https://nitter.privacydev.net/{id}/rss" where user_id="{id}" and url like "%nitter%"')
        db.commit()

    db.close()


def transf_anas_image3():
    '''
    批量更换旧语录中的图片url为本地路径
    '''
    db = sqlite3.connect(path+'/db/anas.db')
    cur = db.cursor()
    cur.execute('select * from AnaList') #获取语录清单

    import sys
    sys.path.append("src/plugins/their_ana")
    import model

    names = [name[0] for name in cur.fetchall()]
    for name in names: #对每一个语录进行处理
        cur.execute(f'select * from "_{name}"')
        anas = cur.fetchall()
        print(f"======处理{name}语录=======")
        for ana in anas:
            print("-----START-------")
            by = ana[1]
            ana = ana[0]
            if "url=https://image.qslie.top/i/qqbot" in ana and "[CQ:image" in ana:
                print('[!]存在图片迁移问题，开始处理')
                # 提取图片文件名
                match = re.search(r'\[CQ:image,url=https://image\.qslie\.top/i/qqbot/([^\]]+)\]', ana)
                if match:
                    filename = match.group(1)
                    new_ana = re.sub(r'\[CQ:image,url=https://image\.qslie\.top/i/qqbot/[^\]]+\]', f'[CQ:image,file=file:///E:\\\\rerika\\\\Erikabot\\\\imgs\\\\{filename}]', ana)
                    print('重建语录内容：',new_ana)
                    cur.execute(f'update "_{name}" set ana = ? where ana = ?', (new_ana, ana))
                    db.commit()
            print("------END-------")
        print("====================")

transf_anas_image3()