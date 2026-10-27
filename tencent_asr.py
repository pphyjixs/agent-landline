"""Tencent's official streaming SDK adapter for HT802 8 kHz PCM audio."""
import array
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace
import uuid
import wave


class PcmLeveler:
    """Boost quiet telephone speech in 20 ms frames, preserving PCM timing.

    Do not boost near-silence or attenuate normal speech. A peak ceiling protects
    loud frames (including the handset's hangup click); gains reset per call.
    """
    def __init__(self, max_gain=16):
        self.max_gain = max_gain
        self.gain = 1.0

    def process(self, data):
        samples = array.array('h')
        samples.frombytes(data)
        if sys.byteorder != 'little':
            samples.byteswap()
        for offset in range(0, len(samples), 160):
            frame = samples[offset:offset + 160]
            peak = max(abs(value) for value in frame)
            rms = math.sqrt(sum(value * value for value in frame) / len(frame))
            gain = (max(1.0, min(self.max_gain, 1600 / rms, 28000 / peak))
                    if rms >= 32 else 1.0)
            # Reduce immediately for a loud frame, ramp increases to avoid steps.
            previous = min(self.gain, gain)
            for index, value in enumerate(frame):
                factor = previous + (gain - previous) * (index + 1) / len(frame)
                samples[offset + index] = max(-32768, min(32767, round(value * factor)))
            self.gain = gain
        if sys.byteorder != 'little':
            samples.byteswap()
        return samples.tobytes()


def credentials(config, root):
    path = Path(root) / config.get('credentials_file', 'tencent-asr.local.json')
    values = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    result = {key: str(os.environ.get(env) or values.get(key) or '').strip()
              for key, env in [('app_id', 'TENCENTCLOUD_APP_ID'),
                               ('secret_id', 'TENCENTCLOUD_SECRET_ID'),
                               ('secret_key', 'TENCENTCLOUD_SECRET_KEY')]}
    missing = [key for key, value in result.items() if not value]
    if missing:
        raise ValueError('腾讯云语音识别待配置：请填写 tencent-asr.local.json 中的 ' + '、'.join(missing) + '，然后重启')
    if not result['app_id'].isdigit():
        raise ValueError('腾讯云 app_id 必须为账号中心的数字 APPID')
    return result


class TencentAsrEngine:
    streaming = True

    def __init__(self, config, root):
        self.options = config.get('tencent', {})
        self.auth = credentials(self.options, root)
        from vendor.tencent_speech.common.credential import Credential
        from opencc import OpenCC
        self.converter = OpenCC('t2s') if config.get('simplified', True) else None
        self.model = self.options.get('engine_model_type', '16k_zh_en_2.0')
        if self.options.get('sentence_strategy',0) not in (0,1):
            raise ValueError('sentence_strategy 必须为 0（短句）或 1（段落）')
        if not isinstance(self.model, str) or not self.model.startswith(('8k_', '16k_')):
            raise ValueError('电话音频请选择 8k_ 或 16k_ 引擎，并核对对应实时识别套餐')
        for key, default in [('connect_timeout_seconds', 8), ('final_timeout_seconds', 15)]:
            value = float(self.options.get(key, default))
            if not 1 <= value <= 60:
                raise ValueError(key + ' 必须在 1–60 秒之间')
        if not isinstance(self.options.get('audio_gain_control', True), bool):
            raise ValueError('audio_gain_control 必须为 true 或 false')
        self.max_gain = float(self.options.get('audio_max_gain', 16))
        if not math.isfinite(self.max_gain) or not 1 <= self.max_gain <= 32:
            raise ValueError('audio_max_gain 必须在 1–32 之间')
        # V2 uses a sentence list and a different SDK transport/lifecycle.
        if self.model in ('16k_zh_en_2.0', '16k_zh_en_speaker_2.0'):
            from vendor.tencent_speech.asr.realtime_recognizer_v2 import RealtimeRecognizerV2
            class TelephoneRecognizer(RealtimeRecognizerV2):
                @property
                def status(self):
                    return self._status

                @property
                def ws(self):
                    conn = getattr(self, '_ws_conn', None)
                    return SimpleNamespace(sock=conn, close=conn.close) if conn else None
        else:
            from vendor.tencent_speech.asr.speech_recognizer import SpeechRecognizer
            class TelephoneRecognizer(SpeechRecognizer):
                def create_query_arr(self):
                    return {**super().create_query_arr(), 'input_sample_rate': 8000}
        self.recognizer_type = TelephoneRecognizer
        self.credential = Credential(self.auth['secret_id'], self.auth['secret_key'])
        self.info = {'provider': 'tencent', 'model': self.model, 'device': '腾讯云',
                     'streaming': True, 'sample_rate': 8000,
                     'audio_gain_control': self.options.get('audio_gain_control', True)}

    def start_stream(self, call_id, on_update):
        return TencentStream(self, call_id, on_update)

    def transcribe(self, path):
        with wave.open(str(path), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 8000):
                raise ValueError('腾讯云电话识别需要 8 kHz 单声道 16 位 PCM WAV')
            stream = self.start_stream(str(uuid.uuid4()), lambda *_: None)
            try:
                while data := audio.readframes(1600):
                    stream.feed(data)
                    time.sleep(len(data) / 16000)
                return stream.finish()
            finally:
                stream.cancel()


class TencentStream:
    """One bounded worker per call. SIP event reader never waits on the network."""
    def __init__(self, engine, call_id, on_update):
        self.engine, self.call_id, self.on_update = engine, call_id, on_update
        self.lock = threading.RLock()
        self.audio = queue.Queue(maxsize=25)  # at most five seconds of 200 ms packets
        self.cancelled = threading.Event()
        self.ending = threading.Event()
        self.completed = threading.Event()
        self.done = threading.Event()
        self.segments, self.stable = {}, set()
        self.error = ''
        self.started = time.monotonic()
        self.leveler = PcmLeveler(engine.max_gain) if engine.options.get('audio_gain_control', True) else None
        self.recognizer = engine.recognizer_type(engine.auth['app_id'], engine.credential, engine.model, self)
        self.recognizer.voice_id = str(uuid.uuid4())
        self.recognizer.set_voice_format(1)
        self.recognizer.set_need_vad(1)
        self.recognizer.set_convert_num_mode(1)
        if hasattr(self.recognizer, 'set_extra_param'):
            self.recognizer.connect_timeout = float(engine.options.get('connect_timeout_seconds', 8))
            self.recognizer.set_extra_param('input_sample_rate', 8000)
            self.recognizer.set_sentence_strategy(engine.options.get('sentence_strategy',0))
        for name in ('filter_dirty', 'filter_modal', 'filter_punc', 'vad_silence_time', 'hotword_id', 'hotword_list'):
            if name in engine.options:
                setter = getattr(self.recognizer, 'set_' + name, None)
                if setter:
                    setter(engine.options[name])
                elif name != 'filter_punc':  # V2 has no documented filter_punc parameter.
                    self.recognizer.set_extra_param(name, engine.options[name])
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _text(self):
        raw = ''.join(self.segments[index] for index in sorted(self.segments)).strip()
        return self.engine.converter.convert(raw) if self.engine.converter else raw

    def _fail(self, message):
        with self.lock:
            if self.error or self.cancelled.is_set():
                return
            self.error = message
            text = self._text()
        self.on_update(text, message)

    def on_recognition_start(self, response):
        pass

    def _result(self, response):
        with self.lock:
            if self.cancelled.is_set() or self.done.is_set() or self.error:
                return
            result = response.get('result', {})
            index = int(result.get('index', 0))
            if index in self.stable:
                return
            self.segments[index] = result.get('voice_text_str', '')
            if result.get('slice_type') == 2:
                self.stable.add(index)
            text = self._text()
        self.on_update(text, '')

    on_sentence_begin = _result
    on_recognition_result_change = _result
    def on_sentence_end(self, response):
        if response.get('final') == 1:
            self.on_recognition_complete(response)
        else:
            self._result(response)

    def on_recognition_sentences(self, response):
        for sentence in response.get('sentences', {}).get('sentence_list', []):
            self._result({'result': {'index': sentence['sentence_id'],
                          'slice_type': 2 if sentence.get('sentence_type') == 1 else 1,
                          'voice_text_str': sentence.get('sentence', '')}})

    def on_recognition_complete(self, response):
        if response.get('result'):
            self._result(response)
        self.completed.set()

    def on_fail(self, response):
        # Never echo server messages or exceptions: they can contain signed URLs.
        # Map known failures to actionable, fixed text instead.
        code = str(response.get('code', 'unknown'))
        code = code if code.isdigit() else 'unknown'
        hint = {
            '4001': '请求参数不合法，请核对识别引擎和音频参数',
            '4002': '鉴权失败，请核对 APPID 与 SecretId、SecretKey 是否属于同一账号（APPID 不是账号 ID/UIN）',
            '4003': '当前 APPID 未开通语音识别服务，请在腾讯云控制台开通',
            '4004': '资源包耗尽，请核对实时识别套餐余量和计费设置',
            '4005': '腾讯云账号欠费，请检查账号余额',
            '4008': '电话音频上传超时，服务端长时间未收到音频分片；请检查收音状态和音频转发链路',
        }.get(code, '请检查密钥、实时识别套餐和网络后重新摘机')
        self._fail('腾讯云识别失败（错误码 ' + code + '）：' + hint)

    def feed(self, data):
        if self.error or self.cancelled.is_set() or self.ending.is_set():
            return
        if not data or len(data) > 3200 or len(data) % 2:
            self._fail('电话音频分片格式错误，请重新摘机')
            return
        try:
            self.audio.put_nowait(data)
        except queue.Full:
            self._fail('腾讯云连接过慢，音频缓冲已满；本轮不提交，请重新摘机')

    def _check(self):
        if self.error or self.cancelled.is_set():
            return False
        if self.recognizer.status in (4, 5) and not self.completed.is_set():
            self._fail('腾讯云语音连接中断，请检查网络后重新摘机')
            return False
        return True

    def _run(self):
        try:
            if self.cancelled.is_set():
                return
            self.recognizer.start()
            deadline = time.monotonic() + float(self.engine.options.get('connect_timeout_seconds', 8))
            while self.recognizer.status != 2:
                if not self._check():
                    return
                if time.monotonic() >= deadline:
                    self._fail('腾讯云语音连接超时，请检查网络后重新摘机')
                    return
                self.cancelled.wait(.02)
            next_send = time.monotonic()
            while self._check():
                try:
                    chunk = self.audio.get(timeout=.05)
                except queue.Empty:
                    if self.ending.is_set():
                        break
                    continue
                if self.cancelled.wait(max(0, next_send - time.monotonic())):
                    return
                if not self._check():
                    return
                self.recognizer.write(self.leveler.process(chunk) if self.leveler else chunk)
                next_send = max(next_send, time.monotonic()) + len(chunk) / 16000
            if not self._check():
                return
            if self.cancelled.wait(max(0, next_send - time.monotonic())):
                return
            # SDK stop() performs an unbounded join; send its end frame here and
            # wait on its completion callback with an explicit deadline instead.
            self.recognizer.ws.sock.send(json.dumps({'type': 'end'}))
            deadline = time.monotonic() + float(self.engine.options.get('final_timeout_seconds', 15))
            while not self.completed.wait(.05):
                if not self._check():
                    return
                if time.monotonic() >= deadline:
                    self._fail('等待腾讯云最终识别结果超时，本轮不提交；请重新摘机')
                    return
        except Exception:
            self._fail('腾讯云语音连接或音频发送失败，请检查网络和 SDK 依赖后重新摘机')
        finally:
            self._close_socket()
            self.done.set()

    def _close_socket(self):
        try:
            if self.recognizer.ws:
                self.recognizer.ws.close(timeout=1)
        except Exception:
            pass

    def finish(self):
        self.ending.set()
        timeout = (float(self.engine.options.get('connect_timeout_seconds', 8)) +
                   float(self.engine.options.get('final_timeout_seconds', 15)) + 7)
        if not self.done.wait(timeout):
            self._fail('腾讯云识别结束超时，本轮不提交；请重新摘机')
            self.cancel()
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            if self.cancelled.is_set() or not self.completed.is_set():
                raise RuntimeError('本轮实时识别已取消或未完成，请重新摘机')
            raw = ''.join(self.segments[index] for index in sorted(self.stable)).strip()
            text = self.engine.converter.convert(raw) if self.engine.converter else raw
            return {'text': text, 'raw_text': raw, 'language': self.engine.model,
                    'asr_seconds': round(time.monotonic() - self.started, 2), 'empty': not text,
                    'provider': 'tencent', 'voice_id': self.recognizer.voice_id}

    def cancel(self):
        self.cancelled.set()
        self._close_socket()
