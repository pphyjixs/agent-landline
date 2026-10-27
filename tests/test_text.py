import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from adapters import create_adapter
from speech import ReplyLedger, chunks, sentence_chunks, speech_text
from text_gateway import TextGateway

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
HTML = '''<div data-conversation-content data-conversation-session="session-test">
 <div data-chat-flow-kind="user" data-chat-node-key="u1" data-chat-turn="1"><div data-message-bubble>原有输入</div></div>
 <div data-chat-flow-kind="assistant-step" data-chat-node-key="a1" data-chat-turn="1" data-chat-group-part="response"><p>原有回答</p><button>复制</button></div>
 <div data-composer-card><div data-composer-input contenteditable="true" role="textbox"></div><button aria-label="发送消息" onclick="window.clicks=(window.clicks||0)+1;const t=document.querySelector('[data-composer-input]').textContent;const n=document.createElement('div');n.dataset.chatFlowKind='user';n.dataset.chatNodeKey='u2';n.dataset.chatTurn='2';n.textContent=t;document.querySelector('[data-conversation-content]').prepend(n);document.querySelector('[data-composer-input]').textContent='';">发送</button></div></div>'''


class FixtureTransport:
    def __init__(self, setup=''):
        self.setup = setup
        self.last = None

    def run(self, code, timeout=20):
        data = {'tools':CONFIG['browser']['tools_dir'], 'edge':CONFIG['browser']['browser_path'],
                'html':HTML, 'setup':self.setup, 'code':code}
        result = subprocess.run([CONFIG['runtime']['node'], str(ROOT / 'tests/browser_driver.cjs')],
            input=json.dumps(data), capture_output=True, text=True, encoding='utf-8', timeout=35, check=True)
        self.last = json.loads(result.stdout)
        if self.last.get('error'):
            raise RuntimeError(self.last['error'])
        return self.last.get('result')


class AdapterBrowserTests(unittest.TestCase):
    def adapter(self, setup=''):
        page = create_adapter(CONFIG['browser'], ROOT)
        page.session = 'session-test'
        page.mcp = FixtureTransport(setup)
        return page

    def test_injects_text_and_confirms_single_user_echo(self):
        page = self.adapter()
        self.assertEqual(page.send('你好，这是一条用户输入。'), {'accepted':True,'uncertain':False,'user_key':'u2','turn':'2'})
        self.assertEqual(page.mcp.last['clicks'], 1)
        self.assertEqual(page.mcp.last['draft'], '')

    def test_preserves_existing_draft_without_click(self):
        page = self.adapter("document.querySelector('[data-composer-input]').textContent='请保留草稿'")
        with self.assertRaises(RuntimeError):
            page.send('新输入')
        self.assertEqual(page.mcp.last['clicks'], 0)
        self.assertEqual(page.mcp.last['draft'], '请保留草稿')

    def test_waits_for_react_to_enable_send_after_input(self):
        page = self.adapter("""const button=document.querySelector('button[aria-label]');button.disabled=true;
            document.querySelector('[data-composer-input]').addEventListener('input',()=>setTimeout(()=>button.disabled=false,100));""")
        self.assertTrue(page.send('等待输入状态更新')['accepted'])
        self.assertEqual(page.mcp.last['clicks'], 1)

    def test_refuses_switched_conversation(self):
        page = self.adapter("document.querySelector('[data-conversation-content]').dataset.conversationSession='other-session'")
        with self.assertRaises(RuntimeError):
            page.send('不能发给另一个会话')
        self.assertEqual(page.mcp.last['clicks'], 0)

    def test_snapshot_separates_user_answer_and_reasoning(self):
        page = self.adapter("""const root=document.querySelector('[data-conversation-content]');
            root.insertAdjacentHTML('afterbegin','<div data-chat-flow-kind="assistant-step" data-chat-node-key="thought" data-chat-turn="1" data-chat-group-part="reasoning">不应该读出的思考</div>');""")
        state = page.snapshot()
        self.assertEqual(state['users'][0]['text'], '原有输入')
        self.assertEqual(state['reply']['text'], '原有回答')
        self.assertFalse(state['busy'])

    def test_busy_page_is_not_submitted(self):
        page = self.adapter("document.querySelector('[data-conversation-content]').insertAdjacentHTML('afterbegin','<div data-chat-running>生成中</div>')")
        with self.assertRaises(RuntimeError):
            page.send('新消息')
        self.assertEqual(page.mcp.last['clicks'], 0)

    def test_unconfirmed_send_is_marked_uncertain_and_not_retried(self):
        page = self.adapter("document.querySelector('button[aria-label]').onclick=()=>{window.clicks=(window.clicks||0)+1;}")
        self.assertEqual(page.send('测试消息'), {'accepted':False,'uncertain':True})
        self.assertEqual(page.mcp.last['clicks'], 1)


class TextStateTests(unittest.TestCase):
    def test_long_text_chunks_do_not_lose_content(self):
        text = '一' * 127 + '。你好！再见。'
        parts = chunks(text, 100)
        self.assertTrue(all(len(p) <= 100 for p in parts))
        self.assertEqual(''.join(parts), text)

    def test_sentence_chunks_keep_content_and_small_first_phrase(self):
        text='你好，欢迎使用电话语音对话程序。接下来我会回答你的问题。'+'长'*75+'。'
        parts=sentence_chunks(text,40,20)
        self.assertLessEqual(len(parts[0]),20)
        self.assertTrue(all(len(p)<=40 for p in parts))
        self.assertEqual(''.join(parts),text)

    def test_speech_cleans_markdown(self):
        self.assertEqual(speech_text('## 标题\n[官网](https://example.com) **你好**'), '标题\n官网 你好')

    def test_reply_dedup_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            ledger = ReplyLedger(path)
            reply = {'turn':'2','key':'a2'}
            ledger.mark('session', reply, 'played')
            self.assertTrue(ReplyLedger(path).contains('session', reply))
            self.assertFalse(ReplyLedger(path).contains('other', reply))

    def test_gateway_emits_new_user_and_stable_final_answer_once(self):
        class Adapter:
            state = {'session':'s','url':'http://local','busy':False,'users':[], 'reply':None}
            def connect(self): return copy.deepcopy(self.state)
            def snapshot(self): return copy.deepcopy(self.state)
        adapter, events = Adapter(), []
        gateway = TextGateway(adapter, events.append, 1)
        gateway.connect()
        adapter.state['users'] = [{'key':'u2','turn':'2','text':'新输入'}]
        adapter.state['reply'] = {'key':'a2','turn':'2','text':'回复','streaming':True}
        gateway.poll()
        self.assertEqual([e['event'] for e in events], ['connected','user_text'])
        adapter.state['reply']['streaming'] = False
        with patch('text_gateway.time.monotonic', side_effect=[10,12,14]):
            gateway.poll(); gateway.poll(); gateway.poll()
        self.assertEqual([e['event'] for e in events].count('assistant_text'), 1)


if __name__ == '__main__':
    unittest.main()
