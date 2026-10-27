# 独立网页文本模块

这一层只处理文字，不导入电话、腾讯云 SDK、Torch 或 TTS。默认网页为 `http://127.0.0.1:3080`。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `adapters/base.py` | `TextAdapter` 公共接口，以及用户消息、AI 回复、发送结果类型 |
| `adapters/dsh_web.py` | DSH 专用：绑定对话、注入文字、读取对话；不包含音频逻辑 |
| `adapters/dsh_page_state.js` | DSH DOM 到标准文本快照的转换，区分用户正文、AI 正文、思考过程和运行状态 |
| `browser_mcp.py` | 通用 Edge/Playwright 扩展通信；不依赖 DSH 页面结构 |
| `text_gateway.py` | 独立进程入口，把文本接口转为 stdin/stdout JSONL |
| `adapters/__init__.py` | 按 `browser.adapter` 选择网站实现 |

座机程序 `app.py` 同样通过 `create_adapter()` 使用此接口。网站替换不需要改写 ASR 或 TTS。

## Python 直接调用

```python
import json
from pathlib import Path
from adapters import create_adapter

root = Path(r'C:\Users\Administrator\Desktop\agent-langline\phone-chat')
config = json.loads((root / 'config.json').read_text(encoding='utf-8-sig'))
adapter = create_adapter(config['browser'], root)
try:
    initial = adapter.connect()       # 绑定已打开的一个对话
    result = adapter.send('你好')      # 可直接传 ASR 最终识别文字
    state = adapter.snapshot()       # state['users'] 是用户文字
    if not state['busy'] and state['reply'] and not state['reply']['streaming']:
        ai_text = state['reply']['text']
        # 自己的程序可以把 ai_text 交给任意 TTS。
finally:
    adapter.close()
```

`send()` 返回 `accepted=true` 表示已观察到网页新增对应用户消息；`uncertain=true` 表示点击后未能确认。异常也可能发生在点击之后，调用方不能自动重试。`snapshot()` 只是当前状态，调用方应比较初始基线、等待文本稳定并去重；下述 `TextGateway` 已实现这些步骤。

## 独立进程协议

运行 `text-web.cmd --watch`。stdout 每行一个 UTF-8 JSON 对象；stdin 每行一条 JSON 命令；换行文字会编码为 JSON 字符串中的 `\n`。stdin 关闭或收到 `stop` 后退出。可只运行这一进程，不启动座机和模型。

输入用户文字：

```json
{"command":"send","text":"请介绍一下你自己。","request_id":"my-turn-1"}
```

输出示例（实际 key/session 由网页决定）：

```json
{"event":"connected","session":"session-xxx","url":"http://127.0.0.1:3080/","busy":false}
{"event":"send_result","request_id":"my-turn-1","accepted":true,"uncertain":false}
{"event":"user_text","session":"session-xxx","key":"user-node","turn":"2","text":"请介绍一下你自己。"}
{"event":"assistant_text","session":"session-xxx","key":"answer-node","turn":"2","text":"你好，我是你的 AI 助手。"}
```

`assistant_text` 在 AI 结束运行且回复稳定后发出，每轮一次，可作为另一个程序的 TTS 输入事件。事件与消息用 `session + turn` 对应；同一轮多个网页用户消息会分别发出 user_text。启动时跳过历史。快照只包含当前已渲染消息，程序启动后请勿翻阅更早历史，否则旧页面节点可能被观察为新用户消息。

其他命令：

```json
{"command":"snapshot","request_id":"read-1"}
{"command":"stop"}
```

`snapshot` 返回 `event=snapshot`，含 `users`、`reply`、`busy` 等字段。`error` 事件含 `request_id`、`message` 和 `retry_safe=false`。连接失败发出 `fatal` 并以非零状态退出。网页请求超时、切换会话后，需要处理并重新启动，不会跟随到别的对话。

一次性读取：`text-web.cmd --snapshot`。一次性发送：`text-web.cmd --send "你好"`；如需继续等回复，加 `--watch`，并保持 stdin 打开。

## 另一个程序订阅 AI 文本并调用自己的 TTS

```python
import json, subprocess

root = r'C:\Users\Administrator\Desktop\agent-langline\phone-chat'
python = r'C:\Users\Administrator\Desktop\ai-autoprint\.venv\Scripts\python.exe'
bridge = subprocess.Popen([python, root + r'\text_gateway.py', '--watch'],
    cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    text=True, encoding='utf-8', bufsize=1)
try:
    for line in bridge.stdout:
        event = json.loads(line)
        if event['event'] == 'connected':
            bridge.stdin.write(json.dumps({'command':'send', 'text':'你好'}, ensure_ascii=False) + '\n')
            bridge.stdin.flush()
        elif event['event'] == 'assistant_text':
            print(event['text'])
            # your_tts.synthesize(event['text'])
        elif event['event'] in ('error', 'fatal'):
            print(event)
finally:
    bridge.stdin.close()
    bridge.wait(timeout=30)
```

如 TTS 很慢，建议用自己的工作队列处理事件，持续读取 stdout，避免管道阻塞。`text_gateway.py` 和完整电话程序应择一连接同一个会话，避免两个控制器同时写入输入框。

## 迁移其他网站

1. 新建 `adapters/other_site.py`，实现 `connect/snapshot/send/close` 和绑定后的 `session` 属性。
2. 按 `base.py` 返回标准 `TextSnapshot`，将该站用户消息和 AI 正文转换到 `users/reply`；根据其状态判断 `busy/streaming`，排除思考与工具面板。
3. 在 `adapters/__init__.py` 加一个工厂分支，并设置 `browser.adapter`。
4. 为该站验证发送成功确认、保护草稿、会话切换拒绝、最终文本去重。完整电话程序和外部 TTS 消费方无需感知网页 DOM。

配置中的 DSH 选择器可以处理简单页面版本变化；更换完全不同的网站时，应替换站点适配器，因为会话定位和完成条件通常也不同。
