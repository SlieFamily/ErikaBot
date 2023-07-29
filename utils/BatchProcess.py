
import sqlite3
import os
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


