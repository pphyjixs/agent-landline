import asyncio
import base64
import contextlib
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from app import PhoneChat

ROOT = Path(__file__).resolve().parents[1]


def state(reply=None):
    return {'session':'s','url':'http://local','busy':False,'users':[], 'reply':reply,
            'userKey':'','activeTurn':'','error':'','editor':1,'draft':False,'sendButtons':1}


class Stream:
    def __init__(self):
        self.cancelled = False
        self.audio = []
    def feed(self, value): self.audio.append(value)
    def finish(self): return {'text':'你好，我想和 AI 对话。'}
    def cancel(self): self.cancelled = True


class Page:
    session = 's'
    def __init__(self): self.sent = []; self.state = state()
    def send(self, text):
        self.sent.append(text)
        return {'accepted':True,'uncertain':False,'turn':'2','user_key':'u2'}
    def snapshot(self): return copy.deepcopy(self.state)


class Phone:
    def __init__(self): self.events = asyncio.Queue(); self.commands = []; self.played = []
    async def send(self, value): self.commands.append(value)
    async def request(self, value, timeout, id_key):
        self.played.append(value)
        return {'event':'played'}


class Worker:
    def __init__(self, root): self.root = root; self.texts = []
    async def request(self, value, timeout):
        self.texts.append(value['text'])
        path = self.root / 'data/tts' / (uuid.uuid4().hex+'.pcm')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\0' * 320)
        return {'path':str(path),'seconds':.02}


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
        config['phone']['echo_guard_ms'] = 0
        config['browser'].update(poll_seconds=.01, stable_seconds=.01)
        self.page, self.stream = Page(), Stream()
        engine = type('Engine', (), {'start_stream':lambda *args:self.stream})()
        with patch('app.TencentAsrEngine',return_value=engine), patch('app.create_adapter',return_value=self.page):
            self.app = PhoneChat(config, self.root / 'config.json')
        self.app.phone, self.app.tts = Phone(), Worker(self.root)
        self.app.state, self.app.initial_error = state(), ''
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.app.task:
            self.app.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.app.task
        if self.app.cleanup_tasks:
            await asyncio.gather(*self.app.cleanup_tasks,return_exceptions=True)
        self.temp.cleanup()

    async def until(self, predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(.01)

    async def test_pcm_to_asr_text_to_page_to_tts_and_playback_once(self):
        self.tasks.append(asyncio.create_task(self.app.handle_events()))
        self.tasks.append(asyncio.create_task(self.app.watch_page()))
        await self.app.phone.events.put({'event':'connected','call_id':'call-1'})
        await self.until(lambda:self.app.listening)
        for event in [dict(event='speech_start'), dict(event='audio',pcm=base64.b64encode(b'\0'*320).decode()), dict(event='speech_end',valid=True)]:
            await self.app.phone.events.put({**event,'call_id':'call-1'})
        await self.until(lambda:bool(self.page.sent) and not self.app.processing)
        self.assertEqual(self.page.sent, ['你好，我想和 AI 对话。'])
        self.assertTrue(self.app.awaiting)
        reply = {'key':'a2','turn':'2','text':'你好，欢迎和我交谈。','streaming':False}
        self.page.state = state(reply)
        await self.until(lambda:bool(self.app.phone.played) and not self.app.speaking)
        self.assertEqual(self.app.tts.texts, ['你好，欢迎和我交谈。'])
        self.assertEqual(len(self.app.phone.played),1)
        self.assertTrue(self.app.listening)
        await asyncio.sleep(.06)
        self.assertEqual(len(self.app.phone.played),1)
        self.assertEqual(self.stream.audio,[b'\0'*320])

    async def test_hangup_during_send_suppresses_late_reply(self):
        self.app.call = 'old-call'; self.app.generation = 1; self.app.processing = True
        def send(text):
            self.app.call = ''; self.app.generation = 2
            return {'accepted':True,'uncertain':False,'turn':'2','user_key':'u2'}
        self.page.send = send
        await self.app.finish_utterance(self.stream,True,'old-call',1)
        self.assertFalse(self.app.awaiting)
        self.assertTrue(self.app.ledger.contains('s',{'turn':'2'}))

    async def test_hash_key_cancels_live_recognition_and_resumes(self):
        self.app.call = 'call-1'; self.app.stream = self.stream
        self.tasks.append(asyncio.create_task(self.app.handle_events()))
        await self.app.phone.events.put({'event':'resume_requested','call_id':'call-1'})
        await self.until(lambda:self.app.listening)
        self.assertTrue(self.stream.cancelled)
        self.assertIsNone(self.app.stream)

    async def test_page_poll_keeps_audio_enabled_during_live_recognition(self):
        self.app.call = 'call-1'
        self.app.listening = True
        self.app.stream = self.stream
        self.tasks.append(asyncio.create_task(self.app.watch_page()))
        await asyncio.sleep(.08)
        self.assertTrue(self.app.listening)
        self.assertFalse(any(command.get('command') == 'listen' and not command['value']
                             for command in self.app.phone.commands))

    async def test_next_sentence_synthesis_overlaps_current_playback(self):
        order=[]
        original=self.app.tts.request
        async def synth(value,timeout):
            order.append('synth:'+value['text'])
            return await original(value,timeout)
        self.app.tts.request=synth
        async def play(value,timeout,id_key):
            order.append('play-start')
            await asyncio.sleep(.04)
            order.append('play-end')
            return {'event':'played'}
        self.app.phone.request=play
        self.app.call='call-1'
        await self.app.speak({'key':'a2','turn':'2','text':'第一句话。第二句话。第三句话。'},'call-1',0)
        self.assertLess(order.index('synth:第二句话。'),order.index('play-end'))
        self.assertEqual(self.app.tts.texts,['第一句话。','第二句话。','第三句话。'])
        self.assertEqual(list((self.root/'data/tts').glob('*.pcm')),[])
