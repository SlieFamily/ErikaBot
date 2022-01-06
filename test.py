import httpx
import random
import hashlib
import os
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from nonebot.log import logger
        
token='1479123623671521282'
dcap = dict(DesiredCapabilities.PHANTOMJS)
dcap["phantomjs.page.settings.userAgent"] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36 Edg/96.0.1054.62') #设置user-agent请求头
dcap["phantomjs.page.settings.loadImages"] = False #禁止加载图片
driver=webdriver.PhantomJS(desired_capabilities=dcap)
driver.set_page_load_timeout(20)
driver.set_script_timeout(20)
try:
    driver.get('https://mobile.twitter.com/Twitter')
except:
    logger.error('twitter.com请求超时！')
    driver.execute_script("window.stop()")
data = driver.get_cookies() 
driver.close()
driver.quit()
if data == None:
    logger.error('token初始化失败，请检查网络/代理是否正常！')
    raise Exception('Twitter插件加载失败！请检查代理')
token=data
print(token)

# user_name='nintendo'
# user_id=''
# headers = {
# 'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
# 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36 Edg/94.0.992.38',
# 'x-guest-token': '%s'%token,
# }
# params = (
# ('variables','{"screen_name":"%s","withSafetyModeUserFields":true,"withSuperFollowsUserFields":false}'%(user_name)),
# )
# response = httpx.get('https://mobile.twitter.com/i/api/graphql/B-dCk4ph5BZ0UReWK590tw/UserByScreenName', headers=headers, params=params)
# if response.status_code==200:
#     re=response.json()['data']
#     if re!={}:
#         dict_word=re['user']['result']
#         user_name=dict_word['legacy']['name']
#         user_id=dict_word['rest_id']

# print(response.status_code,user_name,user_id)
