"""Independent text I/O process: JSONL stdin/stdout, no ASR/TTS/phone imports.

Example stdin: {"command":"send","text":"你好","request_id":"turn-1"}
Example stdout: {"event":"assistant_text","session":"...","turn":"2","text":"你好！"}
"""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import time

from adapters import create_adapter


class TextGateway:
    """Observe new text after a baseline; emit one final answer per turn."""
    def __init__(self, adapter, emit, stable_seconds=1):
        self.adapter, self.emit, self.stable_seconds = adapter, emit, stable_seconds
        self.users = set()
        self.replies = set()
        self.candidate = None
        self.since = 0

    def connect(self):
        state = self.adapter.connect()
        self.users.update(user['key'] for user in state['users'])
        if state['reply'] and not state['busy'] and not state['reply']['streaming']:
            self.replies.add(state['reply']['turn'])
        self.emit({'event':'connected', 'session':state['session'], 'url':state['url'], 'busy':state['busy']})
        return state

    def send(self, text, request_id=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise ValueError('text 必须是 1–100000 字符的非空字符串')
        outcome = self.adapter.send(text.strip())
        self.emit({'event':'send_result', 'request_id':request_id, **outcome})
        return outcome

    def poll(self):
        state = self.adapter.snapshot()
        for user in state['users']:
            if user['key'] not in self.users:
                self.users.add(user['key'])
                self.emit({'event':'user_text', 'session':state['session'], **user})
        reply = state['reply']
        if not reply or state['busy'] or reply['streaming'] or reply['turn'] in self.replies:
            self.candidate = None
            return state
        candidate = (reply['turn'], reply['key'], reply['text'])
        if candidate != self.candidate:
            self.candidate, self.since = candidate, time.monotonic()
        elif time.monotonic() - self.since >= self.stable_seconds:
            self.replies.add(reply['turn'])
            self.emit({'event':'assistant_text', 'session':state['session'],
                       'key':reply['key'], 'turn':reply['turn'], 'text':reply['text']})
        return state


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description='独立网页文本收发模块，JSONL 输入输出')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('config.json'))
    parser.add_argument('--snapshot', action='store_true', help='读取一次完整文字快照并退出')
    parser.add_argument('--send', help='注入一条文字；与 --watch 一起可继续等待回复')
    parser.add_argument('--watch', action='store_true', help='持续输出新用户文字和最终 AI 回复')
    args = parser.parse_args()
    config_file = args.config.resolve()
    adapter = None
    try:
        options = json.loads(config_file.read_text(encoding='utf-8-sig'))['browser']
        adapter = create_adapter(options, config_file.parent)
        gateway = TextGateway(adapter, emit, options['stable_seconds'])
        state = gateway.connect()
        if args.snapshot:
            emit({'event':'snapshot', **state})
        if args.send is not None:
            gateway.send(args.send)
        if args.snapshot or (args.send is not None and not args.watch):
            return 0
        commands = queue.Queue(maxsize=32)
        def read_commands():
            for line in sys.stdin:
                commands.put(line)
            commands.put(None)
        threading.Thread(target=read_commands, daemon=True).start()
        while True:
            try:
                line = commands.get(timeout=options['poll_seconds'])
            except queue.Empty:
                gateway.poll()
                continue
            if line is None:
                return 0
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('命令必须为 JSON 对象')
                if request.get('command') == 'stop':
                    return 0
                if request.get('command') == 'send':
                    gateway.send(request.get('text'), request.get('request_id'))
                elif request.get('command') == 'snapshot':
                    emit({'event':'snapshot', 'request_id':request.get('request_id'), **adapter.snapshot()})
                else:
                    raise ValueError('command 必须为 send / snapshot / stop')
            except Exception as error:
                emit({'event':'error', 'request_id':request.get('request_id') if isinstance(request, dict) else None,
                      'message':str(error), 'retry_safe':False})
            gateway.poll()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        emit({'event':'fatal', 'message':str(error)})
        return 1
    finally:
        if adapter:
            adapter.close()


if __name__ == '__main__':
    sys.exit(main())
