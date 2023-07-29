import requests
import httpx
from utils.QImage import image_download
import re

url = 'https://px3.rainchan.win/c/540x540_70/img-master/img/2022/06/12/14/03/26/98999570_p16_master1200.jpg'
print(image_download(url,'丹尼',False))


# headers = {
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.36"
# }
# url = 'https://moe.jitsu.top/img/?sort=r18&size=1080p&type=json'

# print("[!]访问图片url中")
# req = httpx.get(url, headers = headers)#, timeout = 5)
# print(req.json()['pics'][0])