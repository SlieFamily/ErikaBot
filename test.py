import requests
import httpx
from pyquery import PyQuery as pq
import re
import feedparser
from utils.HtmlTag import handle_html_tag

url = 'https://rss.mcseekeri.top/twitter/user/kiri_basara'
rss = feedparser.parse(url)
html = rss.entries[0]['summary']
# print(html)
html_pq = pq(html)
msg = handle_html_tag(html_pq)
imgs = [item.attr('src') for item in html_pq('img').items()]
print(msg)
print(imgs)





