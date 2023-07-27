import sqlite3
from utils.QImage import *

# text = '[CQ:image,file=xxxxx,url=https://1.pixiv.com/pid?12345]'

# url = 'file://root/home/erikabot/imgs/text.jpg'

db = sqlite3.connect('db/anas.db')
cur = db.cursor()
name = '测试'
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
            new_ana = cq_image_to(ana,new_url) #转换CQ格式
            if new_ana: 
                print('重建语录内容：',new_ana)
                cur.execute(f'update "_{name}" set ana = "{new_ana}" where ana = "{ana}"')
                db.commit()
            else:
                print("[!]语录修改失败")
        else:
            print("[!]图片下载失败")
    else:
        print('[!]当前语录无图片信息')
    print("------END-------")
print("====================")
