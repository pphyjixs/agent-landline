"""Explicit live smoke: sends one harmless prompt to the bound real DSH chat."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    child = subprocess.Popen([sys.executable, str(ROOT / 'text_gateway.py'), '--watch'],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', bufsize=1)
    events = queue.Queue()
    def read():
        for line in child.stdout:
            events.put(json.loads(line))
        events.put({'event':'process_exited'})
    threading.Thread(target=read, daemon=True).start()
    accepted = user = assistant = False
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            event = events.get(timeout=max(.1, deadline-time.monotonic()))
            kind = event['event']
            print(json.dumps(event, ensure_ascii=False), flush=True)
            if kind == 'connected':
                child.stdin.write(json.dumps({'command':'send', 'request_id':'smoke-1',
                    'text':'这是一条网页语音桥接程序的连通性测试。请只回复“语音桥接测试成功”，不要执行工具。'}, ensure_ascii=False)+'\n')
                child.stdin.flush()
            elif kind == 'send_result':
                accepted = event['accepted']
                if not accepted:
                    raise RuntimeError('Live send was not confirmed')
            elif kind == 'user_text':
                user = True
            elif kind == 'assistant_text':
                assistant = '语音桥接测试成功' in event['text']
                break
            elif kind in ('error','fatal','process_exited'):
                raise RuntimeError(str(event))
        assert accepted and user and assistant, 'Missing send/user/assistant event'
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=25)
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=5)
    print('LIVE_TEXT_SMOKE_OK')


if __name__ == '__main__':
    main()
