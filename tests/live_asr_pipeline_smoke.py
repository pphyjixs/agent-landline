"""Actual Tencent ASR through PCMU/RTP, VAD and concurrent page polling.

Uses loopback SIP only and a fake webpage sink: never sends to the user's chat.
The supplied PCM file must be 8 kHz mono signed PCM16 speech.
"""
import argparse
import asyncio
import copy
import json
import logging
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import JsonProcess, PhoneChat


def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


class TextSink:
    session='asr-regression'
    def __init__(self): self.sent=[]
    def snapshot(self):
        return {'session':self.session,'url':'http://test','busy':False,'users':[],
                'reply':None,'userKey':'','activeTurn':'','error':'','editor':1,'draft':False,'sendButtons':1}
    def send(self,text):
        self.sent.append(text)
        return {'accepted':True,'uncertain':False,'turn':'1','user_key':'u1'}


async def main(pcm,noise_amplitude=0):
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    config['asr']['tencent']['credentials_file']=str(ROOT/'tencent-asr.local.json')
    config['browser']['poll_seconds']=.05
    config['phone'].update(local_address='127.0.0.1',device_address='127.0.0.1',
                           sip_port=free_port(),rtp_port=free_port(),device_sip_port=free_port())
    page=TextSink()
    with tempfile.TemporaryDirectory(prefix='dsh-asr-regression-') as directory:
        config_file=Path(directory)/'config.json'
        config_file.write_text(json.dumps(config),encoding='utf-8')
        with patch('app.create_adapter',return_value=page):
            app=PhoneChat(config,config_file)
        app.state=page.snapshot();app.initial_error=''
        app.phone=await JsonProcess.start([config['runtime']['node'],str(ROOT/'sip/bridge.mjs'),str(config_file)],'phone-bridge',config_file.parent)
        tasks=[asyncio.create_task(app.handle_events()),asyncio.create_task(app.watch_page())]
        simulator=None
        try:
            await app.phone.send({'command':'ready','value':True})
            await asyncio.sleep(.2)
            simulator=await asyncio.create_subprocess_exec(config['runtime']['node'],str(ROOT/'tests/ht802_simulator.mjs'),
                str(config_file),str(pcm),str(noise_amplitude),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,creationflags=0x08000000 if sys.platform=='win32' else 0)
            async with asyncio.timeout(30):
                while not page.sent or app.processing:
                    for task in tasks:
                        if task.done(): await task
                    await asyncio.sleep(.05)
            print(json.dumps({'recognized':page.sent,'web_poller_active':not tasks[1].done()},ensure_ascii=False))
            assert '电话' in page.sent[0] and '你好' in page.sent[0]
            print('LIVE_RTP_VAD_ASR_CONCURRENT_POLL_OK')
        finally:
            if simulator:
                simulator.stdin.close()
                try: await asyncio.wait_for(simulator.wait(),3)
                except asyncio.TimeoutError:
                    simulator.kill();await simulator.wait()
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if app.stream:await asyncio.to_thread(app.stream.cancel)
            if app.task:await app.task
            app.call=''
            await app.phone.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('pcm',type=Path)
    parser.add_argument('--noise-amplitude',type=int,default=0)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    asyncio.run(main(args.pcm.resolve(),args.noise_amplitude))
