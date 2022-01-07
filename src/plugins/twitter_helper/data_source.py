import httpx
import random
import hashlib
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from nonebot.log import logger

# 初始化
def init():
    token=''
    option = Options()
    option.add_argument('--headless') #指定参数选项，创建无界面浏览器
    option.add_argument('--no-sandbox')
    option.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=option)
    try:
        driver.get('https://mobile.twitter.com/Twitter')
    except:
        logger.error('twitter.com请求超时！')
        driver.execute_script("window.stop()")
    data = driver.get_cookie('gt') 
    driver.close()
    driver.quit()
    if data == None:
        logger.error('token初始化失败,已使用默认token.可能存在致命问题,请检查代理!')
        token='1479467704943849475'
        return token
    token = data['value']
    return token

# 获取用户信息    
async def get_user_info(name:str,token:str):
    user_name=''
    user_id=''
    headers = {
    'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36 Edg/94.0.992.38',
    'x-guest-token': '%s'%token,
    }
    params = (
    ('variables','{"screen_name":"%s","withSafetyModeUserFields":true,"withSuperFollowsUserFields":false}'%(name)),
    )
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get('https://mobile.twitter.com/i/api/graphql/B-dCk4ph5BZ0UReWK590tw/UserByScreenName', headers=headers, params=params)
        except:
            logger.error('twitter.com访问超时，请检查代理/网络设置！')
            logger.error('获取用户信息失败')
            return '',''
    if response.status_code==200:
        re=response.json()['data']
        if re!={}:
            dict_word=re['user']['result']
            user_name=dict_word['legacy']['name']
            user_id=dict_word['rest_id']
    return user_name,user_id

# 获取最新推文
async def get_latest_tweet(user_id,token):
    headers = {
    'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36 Edg/94.0.992.38',
    'x-guest-token': '%s'%token,
    }
    params = (
    ('variables', '{"userId":"%s","count":2,"withTweetQuoteCount":true,"includePromotedContent":true,"withSuperFollowsUserFields":false,"withUserResults":true,"withBirdwatchPivots":false,"withReactionsMetadata":false,"withReactionsPerspective":false,"withSuperFollowsTweetFields":false,"withVoice":true}'%user_id),
    )
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get('https://mobile.twitter.com/i/api/graphql/OMMpfG9VCdQAK0KHaU1RSQ/UserTweets', headers=headers, params=params)
        except:
            logger.error('twitter.com访问超时，请检查代理/网络设置！')
            logger.error('获取推文失败！')
            return '',{}
    logger.success('刷新推文成功！')
    dict_word = response.json()
    data = dict_word['data']['user']['result']['timeline']['timeline']['instructions'][0]['entries']
    return data[0]['sortIndex'],data

# 获取tweet详情    
def get_tweet_details(data):
    name = data[0]['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['name']
    screen_name = data[0]['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['screen_name']
    quote = data[0]['content']['itemContent']['tweet_results']['result']
    data = retweet = data[0]['content']['itemContent']['tweet_results']['result']['legacy']
    is_quote = False
    is_retweet = False
    text=''
    translate=''
    url=''
    tweet_id=data['id_str']
    media=[]
    if quote.get('quoted_status_result') != None:
        is_quote = True
        quote = quote['quoted_status_result']['result']
    if retweet.get('retweeted_status_result') != None:
        is_retweet = True 
        retweet = retweet['retweeted_status_result']['result']
    if is_quote:
        text='您关注的 {} 推特更新了：\n'.format(name)+data['full_text']+'\n'
        translate=data['full_text']+'\n'
        media_data=data['entities']
        if media_data.get('media')!=None:
            media_data=media_data['media']
            for img in media_data:
                media.append(img['media_url_https'])
        quote_name=quote['core']['user_results']['result']['legacy']['name']
        text+='引用了 {} 的推文：\n'.format(quote_name)
        quote_text=quote['legacy']['full_text']
        text+=quote_text+'\n'
        url='推文地址：\nhttps://twitter.com/'+screen_name+'/status/'+tweet_id+'\n'
        translate+=quote_text+'\n'
        media_data=quote['legacy']['entities']
        if media_data.get('media')!=None:
            media_data=media_data['media']
            for img in media_data:
                media.append(img['media_url_https'])

    elif is_retweet:
        text='您关注的 {} 推特更新了：\n'.format(name)
        retweet_name=retweet['core']['user_results']['result']['legacy']['name']
        text+='转发了 {} 的推文：\n'.format(retweet_name)
        retweet_text=retweet['legacy']['full_text']
        text+=retweet_text+'\n'
        url='推文地址：\nhttps://twitter.com/'+screen_name+'/status/'+tweet_id+'\n'
        translate=retweet_text+'\n'
        media_data=retweet['legacy']['entities']
        if media_data.get('media')!=None:
            media_data=media_data['media']
            for img in media_data:
                media.append(img['media_url_https'])
    else:
        text='您关注的 {} 推特更新了：\n'.format(name)+data['full_text']+'\n'
        translate=data['full_text']+'\n'
        url='推文地址：\nhttps://twitter.com/'+screen_name+'/status/'+tweet_id+'\n'
        media_data=data['entities']
        if media_data.get('media')!=None:
            media_data=media_data['media']
            for img in media_data:
                media.append(img['media_url_https'])
    return text,translate,media,url
    
# 百度翻译
async def baidu_translate(appid,query,token):
    if appid=='' or query=='' or token=='':
        return ''
    text=''
    salt=str(random.randint(32768,65536))
    sign=appid+query+salt+token
    md5=hashlib.md5()
    md5.update(sign.encode('utf-8'))
    sign=md5.hexdigest()
    param={'q':query,'from':'auto','to':'zh','appid':appid,'salt':salt,'sign':sign}
    url='https://fanyi-api.baidu.com/api/trans/vip/translate'
    async with httpx.AsyncClient() as client:
        try:
            result=await client.get(url=url,params=param)
        except:
            logger.error('fanyi-api.baidu.com访问超时，请检查网络设置！')
            logger.error('翻译失败')
            return ''
    if result.status_code!=200:
        return text
    data=result.json()
    if data.get('error_code')!=None:
        return text
    data=data['trans_result']
    for row in data:
        text+=row['dst']+'\n'
    return '推文翻译：\n'+text
