"""Opt-in native image check against DSH; one model call, no QQ sends."""
import argparse
import asyncio
import base64
import io
import logging
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_agent_chat import ROOT, dsh, load_config, package
import importlib
clean_reply = importlib.import_module(package.__name__ + '.domain').clean_reply


async def run():
    picture = Image.new('RGB', (240, 120), 'white')
    draw = ImageDraw.Draw(picture)
    draw.rectangle((15, 20, 95, 100), fill='red')
    draw.ellipse((145, 20, 225, 100), fill='blue')
    output = io.BytesIO()
    picture.save(output, format='JPEG', quality=90)
    image = {'type': 'image', 'mediaType': 'image/jpeg', 'name': 'qq-image-1.jpg',
             'data': base64.b64encode(output.getvalue()).decode('ascii')}
    client = dsh.DshClient(load_config(private_file=ROOT / '.env.agent_chat'))
    sid = None
    try:
        await client.policy()
        sid = await client.create_session()
        answer = clean_reply(await client.reply(sid, 'QQ_CHAT_EVENT image-probe\n'
            '这是独立读图测试。请只说图中左边和右边分别是什么颜色、什么几何形状；看不到就直说，不要猜。', [image]), 600)
        print('REPLY:', answer)
        if not all(word in answer for word in ['红', '方', '蓝', '圆']):
            raise dsh.BridgeError('image_recognition_not_confirmed')
        print('PASS: image bytes reached the configured DSH model and shapes/colors were recognized; no QQ sends')
    finally:
        try:
            if sid:
                await client.stop(sid)
        finally:
            await client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-model-call', action='store_true', required=True)
    parser.parse_args()
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except dsh.BridgeError as error:
        print('FAIL:', str(error))
        sys.exit(1)
    except Exception:
        print('FAIL: image_probe_error')
        sys.exit(1)
