"""HT802 -> Tencent ASR -> an existing DSH Web chat -> Qwen3-TTS -> HT802."""
import argparse
import asyncio
import base64
import contextlib
import json
import logging
import math
import os
from pathlib import Path
import socket
import sys
import time
import uuid

from adapters import create_adapter
from speech import ReplyLedger, sentence_chunks, speech_text
from tencent_asr import TencentAsrEngine, credentials

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger('phone-chat')


def load_config(path):
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    for section in ('runtime', 'browser', 'phone', 'asr', 'tts'):
        if not isinstance(config.get(section), dict):
            raise ValueError(f'缺少配置节：{section}')
    specs = {
        'phone': {'sip_port':(1024,65535), 'device_sip_port':(1024,65535), 'rtp_port':(1024,65535),
                  'max_call_seconds':(10,86400), 'media_timeout_seconds':(2,120), 'vad_rms':(1,10000),
                  'silence_ms':(200,10000), 'min_speech_ms':(20,3000), 'pre_roll_ms':(0,2000),
                  'max_utterance_seconds':(2,55), 'echo_guard_ms':(0,5000)},
        'browser': {'poll_seconds':(.1,10), 'stable_seconds':(.1,10),
                    'reply_timeout_seconds':(10,7200), 'operation_timeout_seconds':(15,120)},
        'tts': {'chunk_chars':(10,500), 'max_new_tokens':(128,8192), 'timeout_seconds':(10,1800)},
    }
    optional_specs = {
        'phone': {'noise_multiplier':(1,10), 'noise_end_multiplier':(1,10), 'noise_max_rms':(1,10000),
                  'noise_window_ms':(100,10000), 'vad_high_pass_hz':(0,1000), 'start_speech_ms':(0,500),
                  'long_utterance_ms':(1000,50000), 'long_silence_ms':(100,2000)},
        'tts': {'first_chunk_chars':(5,100), 'max_seq_len':(256,4096)},
    }
    for section, fields in optional_specs.items():
        for key, limits in fields.items():
            if key in config[section]:
                specs[section][key] = limits
    for section, fields in specs.items():
        for key, (low, high) in fields.items():
            value = config[section].get(key)
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{section}.{key} 必须在 {low}–{high} 之间')
            if key not in ('poll_seconds', 'stable_seconds', 'noise_multiplier', 'noise_end_multiplier') and not isinstance(value, int):
                raise ValueError(f'{section}.{key} 必须为整数')
    if config['phone']['sip_port'] == config['phone']['rtp_port']:
        raise ValueError('SIP 与 RTP 端口不能相同')
    for key in ('local_address', 'device_address'):
        socket.inet_pton(socket.AF_INET, config['phone'][key])
    if config['tts']['mode'] not in ('custom_voice', 'voice_design', 'voice_clone'):
        raise ValueError('无效的 tts.mode')
    if config['tts']['dtype'] not in ('bfloat16','float16','float32'):
        raise ValueError('无效的 tts.dtype')
    if config['tts'].get('backend','official') not in ('official','cuda_graph'):
        raise ValueError('tts.backend 必须为 official 或 cuda_graph')
    for key in ('do_sample','prefetch','warmup_inference'):
        if key in config['tts'] and not isinstance(config['tts'][key],bool):
            raise ValueError('tts.'+key+' 必须为布尔值')
    if config['phone'].get('noise_end_multiplier',1) > config['phone'].get('noise_multiplier',10):
        raise ValueError('noise_end_multiplier 不能大于 noise_multiplier')
    from urllib.parse import urlsplit
    if urlsplit(config['browser']['url']).scheme not in ('http','https'):
        raise ValueError('browser.url 必须为 HTTP(S) 地址')
    for key in ('editor_selector', 'assistant_selector', 'user_selector', 'busy_selector', 'send_selector'):
        if not config['browser'].get(key):
            raise ValueError('缺少 browser.' + key)
    if not isinstance(config['tts'].get('preload'), bool) or not isinstance(config.get('log_transcripts'), bool):
        raise ValueError('preload 和 log_transcripts 必须为布尔值')
    return config


class JsonProcess:
    """One reader per child; command replies cannot steal telephone events."""
    def __init__(self, process, label, log_file):
        self.process, self.label, self.log_file = process, label, log_file
        self.events = asyncio.Queue(maxsize=512)
        self.pending = {}
        self.reader = asyncio.create_task(self._read())

    @classmethod
    async def start(cls, command, label, root):
        log_file = (root / 'data' / f'{label}.log').open('ab')
        env = {**os.environ, 'PYTHONIOENCODING':'utf-8', 'PYTHONUNBUFFERED':'1'}
        try:
            process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=log_file, cwd=root, env=env,
                creationflags=0x08000000 if os.name == 'nt' else 0)
        except BaseException:
            log_file.close()
            raise
        return cls(process, label, log_file)

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                value = json.loads(line)
                ident = value.get('request_id') or value.get('id')
                waiter = self.pending.get(ident)
                if waiter is not None and not waiter.done():
                    if value.get('error'):
                        waiter.set_exception(RuntimeError(value['error']))
                    else:
                        waiter.set_result(value)
                else:
                    self.events.put_nowait(value)
        except Exception as error:
            LOG.error('%s 事件读取失败：%s', self.label, type(error).__name__)
            self.process.kill()
        finally:
            for waiter in self.pending.values():
                if not waiter.done():
                    waiter.set_exception(RuntimeError(self.label + ' 已退出'))
            # A full queue is itself fatal: discard stale audio before reporting.
            while self.events.full():
                self.events.get_nowait()
            self.events.put_nowait({'event':'fatal', 'error':self.label + ' 已退出'})

    async def send(self, value):
        if self.process.returncode is not None:
            raise RuntimeError(self.label + ' 已退出')
        self.process.stdin.write((json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8'))
        await self.process.stdin.drain()

    async def request(self, value, timeout, id_key='id'):
        ident = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.send({**value, id_key:ident})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(ident, None)

    async def close(self):
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        await self.reader
        self.log_file.close()


class PhoneChat:
    def __init__(self, config, config_file):
        self.config, self.config_file = config, config_file
        self.root = config_file.parent
        (self.root / 'data/tts').mkdir(parents=True, exist_ok=True)
        self.page = create_adapter(config['browser'], self.root)
        self.engine = TencentAsrEngine(config['asr'], self.root)
        self.ledger = ReplyLedger(self.root / 'data/replies.json')
        self.phone = self.tts = None
        self.call = ''
        self.stream = None
        self.listening = False
        self.processing = False
        self.speaking = False
        self.blocked = False
        self.awaiting = 0.0
        self.state = None
        self.task = None
        self.generation = 0
        self.candidate = None
        self.candidate_since = 0
        self.pickup_turns = set()
        self.cleanup_tasks = set()

    async def listen(self, value):
        if self.call and value != self.listening:
            await self.phone.send({'command':'listen', 'call_id':self.call, 'value':value})
        self.listening = value

    async def maybe_listen(self):
        # An active recognizer still needs telephone audio until speech_end.
        # Disabling the bridge here resets its VAD and drops that end event.
        if self.stream is not None:
            return
        value = bool(self.call and self.state and not self.state['busy'] and not
                     (self.processing or self.speaking or self.awaiting or self.blocked))
        await self.listen(value)

    def partial(self, call, generation, text, error):
        if call != self.call or generation != self.generation:
            return
        if error:
            LOG.error('%s', error)
        elif self.config['log_transcripts']:
            LOG.info('识别中：%s', text)

    async def handle_events(self):
        while True:
            event = await self.phone.events.get()
            kind = event['event']
            if kind == 'fatal':
                raise RuntimeError(event['error'])
            if kind == 'listening':
                LOG.info('电话监听就绪：%s:%s，等待摘机', event['address'], event['port'])
            elif kind == 'connected':
                self.call = event['call_id']
                self.generation += 1
                self.blocked = False
                self.listening = False
                self.pickup_turns = {user['turn'] for user in self.state.get('users', [])} if self.state else set()
                if self.state:
                    self.pickup_turns.add(self.state.get('activeTurn', ''))
                LOG.info('电话已接通，等待提示音后说话；停顿约 %.1f 秒自动发送', self.config['phone']['silence_ms']/1000)
                # Do not tie the new handset to a previous call's pending answer.
                if self.state and self.state.get('reply'):
                    self.ledger.mark(self.page.session, self.state['reply'], 'pickup-baseline')
                await asyncio.sleep(.2 + self.config['phone']['echo_guard_ms']/1000)
                await self.maybe_listen()
            elif kind == 'ended':
                LOG.info('电话已挂断：%s', event['reason'])
                self.call = ''; self.listening = False; self.generation += 1
                self.awaiting = 0
                if self.stream:
                    await asyncio.to_thread(self.stream.cancel)
                    self.stream = None
            elif kind == 'speech_start':
                if self.call != event['call_id'] or self.processing or self.blocked or self.speaking or self.awaiting:
                    continue
                call, generation = self.call, self.generation
                loop = asyncio.get_running_loop()
                self.stream = self.engine.start_stream(uuid.uuid4().hex,
                    lambda text, error: loop.call_soon_threadsafe(self.partial, call, generation, text, error))
                LOG.info('检测到说话，开始实时上传电话音频（噪声=%s，开始门限=%s，结束门限=%s）',
                         event.get('noise_rms','?'),event.get('start_threshold','?'),event.get('end_threshold','?'))
            elif kind == 'audio':
                if self.call == event['call_id'] and self.stream:
                    self.stream.feed(base64.b64decode(event['pcm'], validate=True))
            elif kind == 'speech_end':
                if self.call != event['call_id']:
                    continue
                self.listening = False
                stream, self.stream = self.stream, None
                if stream:
                    LOG.info('语音分段：%s，停顿 %s ms，正在取得最终识别结果',event.get('reason','silence'),event.get('silence_ms','?'))
                    self.processing = True
                    self.task = asyncio.create_task(self.finish_utterance(stream, event['valid'], self.call, self.generation))
            elif kind == 'resume_requested':
                # Explicit handset recovery after an uncertain send; never resend.
                if not self.processing and not self.speaking:
                    if self.stream:
                        await asyncio.to_thread(self.stream.cancel)
                        self.stream = None
                        self.generation += 1
                    self.blocked = False; self.awaiting = 0
                    self.initial_error = self.state['error'] if self.state else ''
                    await self.maybe_listen()
            elif kind in ('error', 'play_failed'):
                LOG.error('电话接口：%s', event.get('error', kind))

    async def finish_utterance(self, stream, valid, call, generation):
        try:
            if not valid:
                await asyncio.to_thread(stream.cancel)
                return
            result = await asyncio.to_thread(stream.finish)
            if call != self.call or generation != self.generation:
                return
            text = result['text'].strip()
            if not text:
                LOG.info('本轮未识别到文字，继续收音')
                return
            LOG.info('识别完成：%s', text if self.config['log_transcripts'] else f'{len(text)} 字')
            # Persist only unsent/uncertain input for operator recovery.
            pending = self.root / 'data/pending-input.json'
            pending.write_text(json.dumps({'text':text, 'session':self.page.session,
                                          'status':'sending'}, ensure_ascii=False, indent=2), encoding='utf-8')
            try:
                outcome = await asyncio.to_thread(self.page.send, text)
            except Exception:
                self.blocked = call == self.call and generation == self.generation
                LOG.error('网页发送未确认，已停止自动发送；文字保存在 data/pending-input.json。核对网页后按座机 # 恢复')
                return
            if not outcome['accepted']:
                self.blocked = call == self.call and generation == self.generation
                LOG.error('网页可能已发送，程序不会重发。核对网页后按座机 # 恢复')
                return
            pending.unlink(missing_ok=True)
            if call != self.call or generation != self.generation:
                if outcome.get('turn'):
                    self.ledger.mark(self.page.session, {'turn':outcome['turn'], 'key':outcome.get('user_key','')}, 'hangup-during-send')
                return
            self.initial_error = self.state['error'] if self.state else ''
            self.awaiting = time.monotonic()
            LOG.info('已通过 DSH Web 发送，等待 AI 回复')
        except Exception as error:
            LOG.error('本轮识别失败：%s', error)
        finally:
            await asyncio.to_thread(stream.cancel)
            self.processing = False
            await self.maybe_listen()

    async def speak(self, reply, call, generation):
        self.speaking = True
        await self.listen(False)
        self.ledger.mark(self.page.session, reply, 'playback-started')
        prefetch = None
        started = time.monotonic()
        async def synthesize(part):
            return await self.tts.request({'command':'synthesize','text':part},self.config['tts']['timeout_seconds'])
        try:
            text = speech_text(reply['text'])
            LOG.info('开始合成并播报：%s', text if self.config['log_transcripts'] else f'{len(text)} 字')
            parts = sentence_chunks(text,self.config['tts']['chunk_chars'],self.config['tts'].get('first_chunk_chars',20))
            for index,part in enumerate(parts):
                if call != self.call or generation != self.generation:
                    return
                if prefetch:
                    audio = await asyncio.shield(prefetch)
                    prefetch = None
                else:
                    audio = await synthesize(part)
                path = Path(audio['path'])
                try:
                    if call != self.call or generation != self.generation:
                        return
                    if index == 0:
                        LOG.info('首段音频就绪，用时 %.2f 秒（后端=%s）',time.monotonic()-started,audio.get('backend','official'))
                    if self.config['tts'].get('prefetch',True) and index+1 < len(parts):
                        prefetch = asyncio.create_task(synthesize(parts[index+1]))
                    await self.phone.request({'command':'play', 'call_id':call, 'path':str(path)},
                                             audio['seconds'] + 15, id_key='request_id')
                finally:
                    path.unlink(missing_ok=True)
            self.ledger.mark(self.page.session, reply, 'played')
            LOG.info('播报完成，可以继续说话')
        except Exception as error:
            self.blocked = True
            LOG.error('语音播报失败：%s。核对设备后按座机 # 恢复', error)
        finally:
            if prefetch:
                # An abandoned next phrase still needs its PCM removed after
                # the sequential worker completes it. Keep this task owned.
                async def discard(task):
                    try:
                        leftover = await task
                        Path(leftover['path']).unlink(missing_ok=True)
                    except (Exception,asyncio.CancelledError):
                        return
                cleanup = asyncio.create_task(discard(prefetch))
                self.cleanup_tasks.add(cleanup)
                cleanup.add_done_callback(self.cleanup_tasks.discard)
            await asyncio.sleep(self.config['phone']['echo_guard_ms']/1000)
            self.speaking = False
            await self.maybe_listen()

    async def watch_page(self):
        while True:
            try:
                state = await asyncio.to_thread(self.page.snapshot)
                self.state = state
                if state['busy']:
                    # Preserve a live caller utterance; its final send checks
                    # browser availability again and never overwrites a draft.
                    if not self.stream:
                        await self.listen(False)
                    self.candidate = None
                else:
                    reply = state.get('reply')
                    if reply and not reply['streaming'] and not self.ledger.contains(self.page.session, reply):
                        candidate = (reply['turn'], reply['key'], reply['text'])
                        if candidate != self.candidate:
                            self.candidate, self.candidate_since = candidate, time.monotonic()
                        elif time.monotonic() - self.candidate_since >= self.config['browser']['stable_seconds']:
                            if not self.call:
                                self.ledger.mark(self.page.session, reply, 'no-active-call')
                                self.awaiting = 0
                            elif reply['turn'] in self.pickup_turns:
                                self.ledger.mark(self.page.session, reply, 'previous-call-turn')
                            elif not (self.processing or self.speaking or self.stream or self.blocked):
                                self.awaiting = 0
                                self.task = asyncio.create_task(self.speak(reply, self.call, self.generation))
                                # Set synchronously before the task's first await.
                                self.speaking = True
                    if self.awaiting and state['error'] != self.initial_error:
                        self.awaiting = 0
                        self.blocked = True
                        LOG.error('DSH 本轮出现错误，请查看网页；处理后按座机 # 恢复')
                    await self.maybe_listen()
                if self.awaiting and time.monotonic() - self.awaiting > self.config['browser']['reply_timeout_seconds']:
                    self.awaiting = 0; self.blocked = True
                    LOG.error('等待 AI 回复超时，请查看网页；核对后按座机 # 恢复')
            except Exception as error:
                self.blocked = True
                await self.listen(False)
                # A missing tab/session cannot be recovered by sending elsewhere.
                raise RuntimeError('DSH 对话读取失败，已停止电话输入；请重新打开绑定对话并重启') from error
            await asyncio.sleep(self.config['browser']['poll_seconds'])

    async def run(self):
        try:
            LOG.info('连接 Edge 中已打开的 DSH 对话；首次连接请允许 Playwright 扩展')
            self.state = await asyncio.to_thread(self.page.connect)
            self.initial_error = self.state['error']
            LOG.info('已绑定 DSH 会话：%s', self.page.session)
            if self.state.get('reply') and not self.state['busy'] and not self.state['reply']['streaming']:
                self.ledger.mark(self.page.session, self.state['reply'], 'startup-baseline')
            self.tts = await JsonProcess.start([self.config['tts']['python'], str(ROOT / 'tts_worker.py'), str(self.config_file)], 'tts-worker', self.root)
            if self.config['tts']['preload']:
                LOG.info('预加载 Qwen3-TTS 模型，首次可能需要几十秒')
                await self.tts.request({'command':'warmup'}, self.config['tts']['timeout_seconds'])
            self.phone = await JsonProcess.start([self.config['runtime']['node'], str(ROOT / 'sip/bridge.mjs'), str(self.config_file)], 'phone-bridge', self.root)
            await self.phone.send({'command':'ready', 'value':True})
            async with asyncio.TaskGroup() as group:
                group.create_task(self.handle_events())
                group.create_task(self.watch_page())
                group.create_task(self.watch_tts())
        finally:
            if self.stream:
                await asyncio.to_thread(self.stream.cancel)
            if self.task:
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.task
            self.call = ''
            if self.phone:
                await self.phone.close()
            if self.tts:
                await self.tts.close()
            if self.cleanup_tasks:
                await asyncio.gather(*self.cleanup_tasks,return_exceptions=True)
            await asyncio.to_thread(self.page.close)

    async def watch_tts(self):
        while True:
            event = await self.tts.events.get()
            if event.get('event') == 'fatal':
                raise RuntimeError('Qwen3-TTS 子进程已退出，请查看 data/tts-worker.log')


async def doctor(config, config_file, browser=False, tts=False, asr=False):
    root = config_file.parent
    paths = [config['runtime']['node'], config['runtime']['python'], config['tts']['python'],
             config['tts']['model_path'], config['browser']['tools_dir'], config['browser']['browser_path']]
    for path in paths:
        if not Path(path).exists():
            raise RuntimeError(f'路径不存在：{path}')
    credentials(config['asr']['tencent'], root)
    LOG.info('配置、腾讯云凭据与本地依赖路径检查通过（未输出密钥）')
    if browser:
        page = create_adapter(config['browser'], root)
        try:
            state = await asyncio.to_thread(page.connect)
            LOG.info('网页绑定成功：session=%s, busy=%s, editor=%s, sendButtons=%s',
                     state['session'], state['busy'], state['editor'], state['sendButtons'])
        finally:
            await asyncio.to_thread(page.close)
    if asr:
        import wave
        audio = root / 'data/asr-silence-test.wav'
        with wave.open(str(audio), 'wb') as stream:
            stream.setparams((1,2,8000,0,'NONE','not compressed'))
            stream.writeframes(b'\0' * 16000)
        try:
            engine = TencentAsrEngine(config['asr'], root)
            result = await asyncio.to_thread(engine.transcribe, audio)
            LOG.info('腾讯云 ASR 鉴权与音频识别响应通过，返回 %d 字', len(result['text']))
        finally:
            audio.unlink(missing_ok=True)
    if tts:
        worker = await JsonProcess.start([config['tts']['python'], str(ROOT / 'tts_worker.py'), str(config_file)], 'tts-worker', root)
        try:
            result = await worker.request({'command':'synthesize','text':'你好，电话语音对话程序已经准备好了。'}, config['tts']['timeout_seconds'])
            LOG.info('Qwen3-TTS 合成通过：%.2f 秒音频，文件 %s', result['seconds'], result['path'])
        finally:
            await worker.close()


def main():
    parser = argparse.ArgumentParser(description='DSH Web 座机实时语音对话')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--doctor', action='store_true', help='本地配置检查')
    parser.add_argument('--check-browser', action='store_true', help='连接已打开的对话，不发送文字')
    parser.add_argument('--test-tts', action='store_true', help='实际合成测试，不播放到座机')
    parser.add_argument('--test-asr', action='store_true', help='实际腾讯云鉴权及一秒静音识别')
    args = parser.parse_args()
    path = args.config.resolve()
    (path.parent / 'data/tts').mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(), logging.FileHandler(path.parent / 'data/phone-chat.log', encoding='utf-8')])
    try:
        config = load_config(path)
        if args.doctor or args.check_browser or args.test_tts or args.test_asr:
            asyncio.run(doctor(config, path, args.check_browser, args.test_tts, args.test_asr))
        else:
            asyncio.run(PhoneChat(config, path).run())
    except KeyboardInterrupt:
        LOG.info('程序已停止，电话端口与模型进程已释放')
    except Exception as error:
        if isinstance(error, BaseExceptionGroup):
            for child in error.exceptions:
                LOG.error('%s', child)
        else:
            LOG.error('%s', error)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
