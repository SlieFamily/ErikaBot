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
    res = re.findall(",(url|file)=((http|https)+://[^\s]*)[,]*\]",text)
    if res:
        url = res[0][1].split(',')[0]
        # 处理 HTML 实体（例如 &amp; -> &）
        from html import unescape
        url = unescape(url)
        return url
    else:
        return ''

def cq_image_to(text:str, url:str='')->str:
    '''
        将原始CQ消息的image格式修改为file-url形式
    '''
    res = get_image_url(text)
    if res : #判断是否为image消息
        if not url:
            url = res #如果没有提供url，直接转换；否则转换为指定url
        ana = re.sub("\[CQ:image[\w\W]*,(file|url)=(http|https)://[^\s]*[\w\W]*\]","[CQ:image,file="+url+"]",text)
        return ana
    return ''

def ntqq_image_to(text:str, url:str='')->str:
    '''
        将原始NTQQ消息的image格式修改为file-url形式
    '''
    res = get_image_url(text)
    if res : #判断是否为image消息
        if not url: url = res #如果没有提供url，直接转换；否则转换为指定url
        else: url = url.replace("\\", "\\\\")
        ana = re.sub("\[CQ:image[\w\W]*,url=(http|https)://[^\s]*[\w\W]*\]","[CQ:image,file="+url+"]",text)
        return ana
    return ''

def image_download(url:str, tag:str, use_timestamp:bool = True)->str:
    '''
        根据所提供的url和tag下载图片并重命名
    '''
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.36"
    }
    print("[!]访问图片url中", url)
    req = requests.get(url, headers = headers, timeout = 5)
    filename = ''
    dirname = 'imgs/'
    if req.content:
        if use_timestamp:
            filename = tag+"_"+str(time.time())+".jpg"
        else:
            filename = tag+".jpg"
        with open(dirname+filename, mode = "wb") as f:
            f.write(req.content) # 下载图片
        print("[!]图片资源下载成功")
        return  filename
    return filename



