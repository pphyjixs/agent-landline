"""Attach to the operator's existing Edge through Playwright MCP extension."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


class BrowserMCP:
    def __init__(self, options, root):
        tools = Path(options['tools_dir'])
        node = tools / 'node.exe'
        cli = tools / 'node_modules/@playwright/mcp/cli.js'
        edge = Path(options['browser_path'])
        for path in (node, cli, edge):
            if not path.is_file():
                raise RuntimeError(f'浏览器依赖不存在：{path}')
        env = os.environ.copy()
        token_file = Path(root) / options['extension_token_file']
        if token_file.is_file():
            token = token_file.read_text(encoding='utf-8-sig').strip()
            if token.startswith('PLAYWRIGHT_MCP_EXTENSION_TOKEN='):
                token = token.split('=', 1)[1].strip().strip('\"\'')
            env.pop('PLAYWRIGHT_MCP_EXTENSION_TOKEN', None)
            if token:
                env['PLAYWRIGHT_MCP_EXTENSION_TOKEN'] = token
        self.messages = queue.Queue()
        self.serial = 0
        self.lock = threading.Lock()
        self.process = subprocess.Popen(
            [str(node), str(cli), '--browser', 'msedge', '--executable-path', str(edge),
             '--extension', '--caps', 'devtools', '--snapshot-mode', 'none', '--timeout-settle', '50'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                    'clientInfo': {'name': 'DSH-Phone-Chat', 'version': '1.0'}}, 20)
            self._write({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.messages.put(None)

    def _write(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def rpc(self, method, params, timeout):
        with self.lock:
            self.serial += 1
            ident = self.serial
            self._write({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params})
            deadline = time.monotonic() + timeout
            while True:
                try:
                    item = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
                except queue.Empty:
                    raise TimeoutError('Edge 连接或操作超时，请检查 Playwright 扩展连接') from None
                if item is None:
                    raise RuntimeError('浏览器连接已退出')
                if item.get('id') != ident:
                    continue
                if 'error' in item:
                    raise RuntimeError('浏览器 RPC 失败')
                return item['result']

    def run(self, code, timeout=20):
        result = self.rpc('tools/call', {'name': 'browser_run_code_unsafe',
                                       'arguments': {'code': code}}, timeout)
        text = '\n'.join(v.get('text', '') for v in result.get('content', []) if v['type'] == 'text')
        if result.get('isError') or '### Result\n' not in text:
            # Tool output may include page contents; keep it out of normal logs.
            raise RuntimeError('浏览器操作失败：页面关闭、会话切换、草稿非空或选择器不匹配；请运行 diagnose.cmd')
        return json.JSONDecoder().raw_decode(text.split('### Result\n', 1)[1].lstrip())[0]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
