import sqlite3
db = sqlite3.connect('anas.db')
cur = db.cursor()
cur.execute('select name from sqlite_master where type="table" and name like "%汐%"')
name = cur.fetchall()[0][0]
print(name)
cur.execute(f'DROP table "{name}"')
db.commit()