"""Measure warmed official and CUDA-graph backends with the same voice/text."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import JsonProcess


async def run(backends):
    original=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    results=[]
    for backend in backends:
        folder=ROOT/'data/tts-benchmark'/backend
        (folder/'data/tts').mkdir(parents=True,exist_ok=True)
        config=json.loads(json.dumps(original))
        config['tts'].update(backend=backend,warmup_inference=True)
        config_file=folder/'config.json'
        config_file.write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
        worker=await JsonProcess.start([config['tts']['python'],str(ROOT/'tts_worker.py'),str(config_file)],'tts-worker',folder)
        try:
            await worker.request({'command':'warmup'},300)
            for index in range(2):
                started=time.monotonic()
                audio=await worker.request({'command':'synthesize','text':'你好，电话语音对话程序已经准备好了。'},300)
                result={'backend':backend,'run':index+1,'speaker':config['tts']['speaker'],
                        'elapsed':round(time.monotonic()-started,3),'synthesis_seconds':audio['synthesis_seconds'],
                        'audio_seconds':audio['seconds'],'path':audio['path']}
                results.append(result)
                print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:
            await worker.close()
    (ROOT/'data/tts-benchmark/results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--include-baseline',action='store_true')
    args=parser.parse_args()
    asyncio.run(run(['official','cuda_graph'] if args.include_baseline else ['cuda_graph']))
