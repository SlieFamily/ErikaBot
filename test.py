import httpx
import json
import sqlite3
import random
import re


db = sqlite3.connect('db/anas.db')
cur = db.cursor()
cur.execute(f'select * from AnaList where ana_name="斯莱"')
cur.execute(f'select * from "_斯莱"')
All_anas = cur.fetchall()
print('-'*45)
print(len(All_anas))
print(All_anas[0][0])
print(All_anas[len(All_anas)][0])
cur.close()
db.close()
    