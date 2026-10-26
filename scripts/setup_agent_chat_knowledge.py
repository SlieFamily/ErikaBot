"""Explicit owner setup of the private loopback tool bridge. Never prints its token."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time


def private_write(path, text):
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        if os.name=='nt':
            owner=os.environ['USERDOMAIN']+'\\'+os.environ['USERNAME']
            subprocess.run(['icacls',str(temporary),'/inheritance:r','/grant:r',owner+':(F)','SYSTEM:(F)'],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as output:
            fd=None;output.write(text)
        os.replace(temporary,path)
    finally:
        if fd is not None:os.close(fd)
        if temporary.exists():temporary.unlink()


def setup(env_path,profile_path,port=8080,apply=False):
    env_path,profile_path=Path(env_path).resolve(),Path(profile_path).resolve()
    if not env_path.is_file() or not (profile_path/'package.json').is_file() or not 1<=port<=65535:
        raise ValueError('Existing private env, DSH profile and valid NoneBot port are required')
    original=env_path.read_text(encoding='utf-8-sig')
    matches=re.findall(r'^AGENT_CHAT_KNOWLEDGE_TOKEN=(.*)$',original,re.M)
    if len(matches)>1:raise ValueError('Duplicate knowledge token setting')
    token=(matches[0].strip().strip('"\'') if matches else '') or secrets.token_hex(32)
    if not re.fullmatch(r'[a-f0-9]{64}',token):raise ValueError('Invalid existing knowledge token')
    file=profile_path/'.agent-chat/knowledge-bridge.json'
    if file.exists():
        existing=json.loads(file.read_text(encoding='utf-8-sig'))
        if existing.get('token')!=token:raise ValueError('Conflicting existing bridge credential; refusing to replace')
    updated=original
    for key,value in {'AGENT_CHAT_MEMORY_ENABLED':'true','AGENT_CHAT_SLANG_ENABLED':'true',
                      'AGENT_CHAT_KNOWLEDGE_TOKEN':token}.items():
        pattern=r'^'+key+r'=.*$'
        if re.search(pattern,updated,re.M):updated=re.sub(pattern,key+'='+value,updated,flags=re.M)
        else:updated=updated.rstrip()+'\n'+key+'='+value+'\n'
    if not apply:return {'applied':False,'origin':f'http://127.0.0.1:{port}','memory':True,'slang':True}
    if original!=updated:
        private_write(env_path.with_name(env_path.name+f'.knowledge-{time.time_ns()}.bak'),original)
    file.parent.mkdir(parents=True,exist_ok=True)
    private_write(file,json.dumps({'version':1,'origin':f'http://127.0.0.1:{port}','token':token})+'\n')
    private_write(env_path,updated)
    return {'applied':True,'origin':f'http://127.0.0.1:{port}','memory':True,'slang':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env',required=True,help='Existing private .env.agent_chat')
    parser.add_argument('--profile',required=True,help='Existing DSH profile directory')
    parser.add_argument('--port',type=int,default=8080,help='NoneBot HTTP port (not DSH port)')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(setup(args.env,args.profile,args.port,args.apply)))
    except Exception:
        parser.exit(1,'Knowledge setup failed. Check paths, duplicate settings, private-file permissions and existing credential consistency.\n')
