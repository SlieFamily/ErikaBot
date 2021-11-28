import httpx
import json

def get_json():
    '''
    提取words的json内容
    '''
    # 推荐使用此方法
    # 调取爆点语录的链接api
    # async with httpx.AsyncClient() as client:
    #     resp = await client.get('https://my-json-server.typicode.com/sliefamily/bdg-bot/db')
    #     json_data = resp.json()

    # 这里是直接读取本地文件的方法
    with open("/home/bdg-bot/db.json",'r',encoding='utf8')as fp:
        json_data = json.load(fp)
        return json_data
    return None

async def get_image(key:str):
    '''
    根据关键词提取image的url
    '''
    try:
        imgs = get_json()['bqb']
        for i in range(0,len(imgs)):
            if imgs[i]["key"] == key:
                return imgs[i]["url"]
    except:
        return "发送失败，数据库维护中……"
    
def update_img(key:str,url:str):
    dats = {"key":key,"url":url}
    print(dats)
    json_data = get_json()
    json_data['bqb'].append(dats)
    with open("/home/bdg-bot/db.json", "w", encoding="utf8") as fp:
        json.dump(json_data, fp,ensure_ascii=False)
        return True
    return False
