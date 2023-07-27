# import httpx
# import json
# import sqlite3
# import random
import re
import requests
import time
import os

def get_image_url(text:str)->str:
    '''
        匹配给定CQ文本中的图片url
    '''
    res = re.findall(",(url|file)=([a-zA-z]+://[^\s]*)[,]*\]",text)
    return res[1] if res else ''

def cq_image_to(text:str, url:str = '')->str:
    '''
        将原始CQ消息的image格式修改为file-url形式
    '''
    res = get_image_url(text)
    if res : #判断是否为image消息
        if not url:
            url = res #如果没有提供url，直接转换；否则转换为指定url
        ana = re.sub("\[CQ:image,[\w\W]+,url=[a-zA-z]+://[^\s]*[,]*[\w\W]*\]","[CQ:image,file="+url+"]",text)
        return ana
    return ''

def image_download(url:str, tag:str)->str:
    '''
        根据所提供的url和tag下载图片并重命名
    '''
    headers = { #请求头
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36'
    }
    req = requests.get(url,headers=headers)
    filename = ''
    dirname = 'imgs/'
    if req.content:
        filename = tag+"_"+str(time.time())+".jpg"
        with open(dirname+filename, mode = "wb") as f:
            f.write(req.content) # 下载图片
        return  filename
    return filename



