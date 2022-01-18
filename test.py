import sqlite3


def IsNotInCard(name,id)->bool: #根据用户名和群号判断是否关注
    DB=sqlite3.connect('twitter.db')
    CUR=DB.cursor()
    CUR.execute('select * from user_list where name like "%{}%"'.format(name))
    screen_name = CUR.fetchall()
    if screen_name == []:
        CUR.close()
        DB.close()
        return True
    screen_name = screen_name[0][0]
    table_name = '_'+screen_name
    CUR.execute('select * from {} where id="{}"'.format(table_name,id))
    data = CUR.fetchall()
    if len(data) == 0:
        CUR.close()
        DB.close()
        return True
    else:
        return False

print(IsNotInCard("菠萝","984401519"))