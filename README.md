# DSH Web 座机语音对话

电话话筒 → HT802 SIP/RTP → 腾讯云实时 ASR → 已打开的 DSH Web 对话 → 读取 AI 最终回复 → 本地 Qwen3-TTS → HT802 → 电话听筒。

文字注入与回复读取已独立为网站适配器；无需电话或 TTS 时可单独运行 `text-web.cmd --watch`，以 JSONL 输出用户和 AI 文字。Python 接口、进程协议和迁移说明见 [TEXT_API.md](TEXT_API.md)。

## 一、先选择使用方式

| 需要做什么 | 运行入口 |
| --- | --- |
| 拿起座机，用语音和网页内的 AI 连续对话 | 双击 `start.cmd` |
| 只向网页输入文字、获取用户文字和 AI 回复，交给自己的程序处理 | 运行 `text-web.cmd --watch` |
| 检查网页连接是否正常，不发送消息 | 双击 `diagnose.cmd` |

本目录位置：`C:\Users\Administrator\Desktop\agent-langline\phone-chat`。

当前电脑的腾讯云密钥、电话地址及模型路径已经配置好，首次使用通常不用安装依赖或修改配置。Qwen3-TTS 由程序自行加载，**无需单独启动它的配音网页**。

## 二、完整座机对话：按这个顺序操作

### 第 1 步：连接座机和 HT802

将座机电话线接到 HT802 的 `PHONE 1`，HT802 网口接电脑或现有局域网，接通设备电源。继续使用 ai-autoprint 已经验证过的接线和设备设置即可。

本机现有配置为：

- 电脑有线地址：`192.168.0.1`。
- HT802 地址：`192.168.0.160`。
- 电脑接收电话信令：UDP `5090`；音频：UDP `15004`。
- HT802 摘机自动拨号：`263`。

### 第 2 步：停止 ai-autoprint 的电话服务

如果 ai-autoprint 正在运行，双击 `C:\Users\Administrator\Desktop\ai-autoprint\stop.cmd` 停止它。它和本程序使用同一组电话端口，不能同时接管座机。未运行时可跳过。

### 第 3 步：启动 DSH Web，打开要使用的对话

如果 DSH Web 已在运行，直接用 **Edge** 打开 [http://127.0.0.1:3080](http://127.0.0.1:3080)。否则，在 PowerShell 中执行：

```powershell
Set-Location 'C:\Users\Administrator\Desktop\agent-langline\deepseek-harness'
pnpm run start:web
```

保留 DSH 的服务窗口，在 Edge 中打开目标对话。首次使用新对话时，先在网页手动发送一句话，确认 AI 能正常回答。

启动电话程序前：

1. 只保留一个该地址的对话标签页；默认会自动绑定它。
2. 等待网页当前任务结束。
3. 清空或自行处理输入框里的草稿、引用和附件，避免它们阻止语音文字提交。

### 第 4 步：可选，先检查网页连接

双击本目录 `diagnose.cmd`。正常时会显示“配置、腾讯云凭据与本地依赖路径检查通过”和“网页绑定成功”，其中 `editor=1`、`sendButtons=1`。

如果出现 Playwright 扩展连接页，请允许连接。程序已复制本机现有扩展令牌，正常情况下自动连接；令牌更换后需更新 `data/browser-extension-token.txt`。

检查结束后关闭诊断窗口即可。诊断不会向对话发送文字，也不会开始电话收音。

### 第 5 步：启动电话程序

双击本目录 **`start.cmd`**，保持这个窗口打开。

程序先连接网页，再加载 TTS 模型。首次加载可能需要几十秒。看到下面的提示后再摘机：

```text
已绑定 DSH 会话：session-...
预加载 Qwen3-TTS 模型，首次可能需要几十秒
电话监听就绪：192.168.0.1:5090，等待摘机
```

### 第 6 步：拿起话筒开始对话

1. 摘机，听到短提示音后说话。例如：“你好，请用一句话介绍你自己。”
2. 说完停顿约 **0.45 秒**。程序会结束这一轮识别，将文字自动填入网页并发送，**不用挂机**。这里是本地停顿检测时间，云端最终结果和网页发送仍需少量时间。
3. 查看网页，应出现刚才的用户消息，随后出现 AI 回复。
4. AI 完成回答后，程序调用本地 Qwen3-TTS，声音通过 HT802 从电话听筒播放。
5. 播报结束后继续说第二句话，重复以上流程。

等待 AI 和播报期间暂停收音，请等听筒播放完成后再说话。目前不支持说话打断播报。长回复先合成短首句，播放时提前生成下一句；生成速度不足时段间仍可能有等待。

首次验收建议在同一通电话内连续说两轮，确认“收音 → 网页发送 → AI 回答 → 听筒播报 → 再次收音”全部正常。

### 第 7 步：结束使用

- 结束这通电话：正常挂机，程序继续等待下次摘机。
- 退出电话程序：在 `start.cmd` 打开的窗口中按 **`Ctrl+C`**，等待退出。
- 下次继续使用：确认 DSH 网页正常，再双击 `start.cmd`。

程序绑定启动时的会话 ID。切换到其他对话、关闭原标签页或网页连接异常时，会停止输入并报告错误。要更换对话，先退出电话程序，再打开新对话并重新启动。

## 三、只使用独立文字模块

这种方式不用接座机，也不加载 ASR 或 TTS。先完成上面“启动 DSH Web，打开要使用的对话”这一步，然后在 PowerShell 执行：

```powershell
Set-Location 'C:\Users\Administrator\Desktop\agent-langline\phone-chat'
.\text-web.cmd --watch
```

看到 `"event": "connected"` 后，输入下面这一整行 JSON 并按回车：

```json
{"command":"send","text":"你好，请用一句话介绍你自己。","request_id":"demo-1"}
```

程序会向当前对话发送文字，并依次输出类似结果：

```json
{"event":"send_result","request_id":"demo-1","accepted":true,"uncertain":false,"user_key":"...","turn":"2"}
{"event":"user_text","session":"session-...","key":"...","turn":"2","text":"你好，请用一句话介绍你自己。"}
{"event":"assistant_text","session":"session-...","key":"...","turn":"2","text":"你好，我是你的 AI 助手。"}
```

你的另一个程序读取 `assistant_text` 事件中的 `text`，即可交给自己的 TTS。用户输入文字在 `user_text.text` 中；使用 `session` 和 `turn` 对应同一轮对话。

输入下面这一行可退出：

```json
{"command":"stop"}
```

仅查看当前文字、不发送消息：

```powershell
.\text-web.cmd --snapshot
```

独立文字模块和完整电话程序请选择一个运行，避免同时操作同一输入框。进程订阅示例、Python 直接调用和迁移其他网站的步骤见 [TEXT_API.md](TEXT_API.md)。

## 四、修改配置

编辑 `config.json`，保存后重启。当前配置及腾讯云密钥已从本机 ai-autoprint 复制，无需重新填写；源码运行时不依赖它的业务程序。

| 配置 | 含义 |
| --- | --- |
| `browser.url` | DSH Web 地址，用于匹配已打开网页的 origin |
| `browser.session_id` | 可选，指定会话 ID；留空时绑定唯一打开的对话 |
| `browser.*_selector` | 网页版本变化时可调整的输入、发送、回复和运行状态选择器 |
| `phone.local_address` / `device_address` | 电脑 `192.168.0.1` / HT802 `192.168.0.160` |
| `phone.sip_port` / `rtp_port` | 本机 UDP `5090` / `15004` |
| `phone.device_sip_port` | HT802 SIP UDP `5060` |
| `phone.silence_ms` | 普通语句停顿阈值，当前 450 毫秒 |
| `phone.vad_rms` | 检测能量下限，当前 300；实际门限还受自适应噪声倍数影响 |
| `phone.noise_multiplier` / `noise_end_multiplier` | 起音/续音噪声倍数，当前 2.6 / 1.5；使用不同门限减少噪声反复触发 |
| `phone.vad_high_pass_hz` | VAD 检测使用 150Hz 高通，减弱低频风扇声；送腾讯云的原始 PCM 不变 |
| `phone.noise_window_ms` / `noise_max_rms` | 当前噪声估计窗口 2000ms、噪声估计上限 1200 |
| `phone.start_speech_ms` / `min_speech_ms` | 当前连续 60ms 起音，至少 160ms 有声才提交，过滤短碰撞声 |
| `phone.long_utterance_ms` / `long_silence_ms` | 连续段超过 12000ms 后，在至少 300ms 的自然停顿处提交 |
| `phone.max_utterance_seconds` | 单轮最长 25 秒，长讲话到上限自动提交 |
| `phone.max_call_seconds` | 单次通话上限，默认一小时 |
| `phone.echo_guard_ms` | 播放后等待回声消退再收音，当前 350ms |
| `asr.tencent.engine_model_type` | 已复用 `16k_zh_en_2.0`，输入为 8k PCM，SDK 指定 input_sample_rate |
| `asr.tencent.credentials_file` | `tencent-asr.local.json`，也支持 `TENCENTCLOUD_*` 环境变量覆盖 |
| `asr.tencent.sentence_strategy` | 当前 0，腾讯云最小语义短句；1 为较长段落，低延迟对话建议保留 0 |
| `tts.root` / `tts.python` | 已安装 Qwen3-TTS 的目录及 Python 环境 |
| `tts.model_path` | 本地模型目录，默认 `Qwen3-TTS-12Hz-1.7B-CustomVoice` |
| `tts.mode` | `custom_voice`、`voice_design` 或 `voice_clone`，须与所选模型匹配 |
| `tts.speaker` / `instruct` | 当前 Serena 温柔女声；指令为“用明亮、清晰、有亲和力的年轻女声说话，语速正常，简洁自然。” |
| `tts.backend` | 当前 `cuda_graph`，使用随项目提供的 faster-qwen3-tts 0.2.6；改为 `official` 可使用原始后端 |
| `tts.reference_audio` / `reference_text` | Base 模型克隆音色时的参考音频和文字 |
| `tts.device` / `dtype` / `attention` | 默认 `cuda:0` / `bfloat16` / `sdpa` |
| `tts.preload` / `warmup_inference` | 均为 true，启动时加载模型、捕获 CUDA Graph 并用短句预热，把首次计算移到摘机前 |
| `tts.first_chunk_chars` / `chunk_chars` | 首段上限 20 字、后续上限 40 字，优先句号/问号等句末或逗号边界 |
| `tts.prefetch` | true，当前段 RTP 播放时提前合成下一段；最多提前一段 |
| `tts.do_sample` | false，优先速度和稳定输出，语气多样性可能降低 |
| `tts.max_new_tokens` / `max_seq_len` | 当前 512 / 1024，前者是生成上限而非截断文字的字数；与短句长度配套 |
| `log_transcripts` | 默认 false，不在日志记录对话正文；开启后记录识别与播报文字 |

TTS 模型在独立进程中常驻，不会每轮重新加载。支持本地已有模型，不自动下载。更换模型时需同时调整 `tts.mode`，如 VoiceDesign 用 `voice_design`、Base 用 `voice_clone`。克隆音色的参考音频使用绝对路径。

### 本次低延迟调整及调参方法

原来的固定阈值 100 将持续服务器噪声当成说话，实际日志中两轮都接近 25 秒上限才提交。现在在非播报阶段估计背景噪声，检测门限为：起音 `max(300, 噪声 × 2.6)`，续音 `max(210, 噪声 × 1.5)`。短于 450ms 的普通句中停顿继续收音；长语段超过 12 秒后可在 300ms 停顿处分段；一直没有停顿时仍以 25 秒为保护上限。这是能量与时长断句，语义句子由腾讯云识别器处理，不会仅凭逗号就强制中断电话收音。

启动窗口会记录“噪声、开始门限、结束门限”和分段原因。若仍经常出现 `duration_limit`，可适当提高 `noise_end_multiplier` 或 `vad_rms`；若说话难以触发，降低 `vad_rms` 或 `noise_multiplier`。如果经常在句中停顿处过早提交，将 `silence_ms` 调至 600，并按需要将 `long_silence_ms` 调至 450。现场噪声未实测，当前参数是经过模拟风扇噪声验证的起点。

TTS 保留已安装的 1.7B CustomVoice 模型，只增加兼容现有 Torch/Transformers 的 CUDA Graph 推理代码。此前使用相同中文测试句、Vivian 音色、预热后，本机原后端两次生成耗时为 **8.625 / 8.375 秒**，加速后为 **1.891 / 1.594 秒**；约快 4～5 倍，实际取决于文字、音频时长及 GPU 占用。当前已按用户要求改为 Serena 温柔女声、正常语速，上述数据和 `data/bright-female-preview.wav` 属于旧 Vivian 配置的测试记录。结果在 `data/tts-benchmark/results.json`。

AI 回复读取的额外等待也已缩短：`browser.poll_seconds=0.2`，`browser.stable_seconds=0.2`。仍等待 AI 本轮结束后才交给 TTS；此版本不是 AI token 或声码器帧级流式播放。

## 五、使用行为与恢复

- 收音阶段音频实时送到腾讯云；检测到停顿后取得最终识别结果，再通过网页发送。`log_transcripts=true` 可查看识别中间结果。
- AI 回复等待网页运行结束且文本稳定后播报，避免把思考过程、工具输出和尚未完成的文本读出来。**不是模型 token 级流式 TTS**。按短句合成，并让下一句计算与当前播放重叠。
- 使用半双工方式，等待 AI 和播放期间暂停收音；暂不支持说话打断播报。网页手动输入得到的新回复，在当前通话期间也会自动播报。
- 启动、重新摘机时跳过已有回复。`data/replies.json` 按会话和轮次去重；失败或中途挂机不会自动重播整段，避免重复。
- 网页发送结果不确定时不会重发，识别文字保存在 `data/pending-input.json`。先检查网页是否已发送，再按座机 `#` 恢复收音；需要重发的文字可人工从该文件复制。确认已发送后文件自动删除。
- 电话挂机会丢弃未提交语音；已发出的网页任务继续运行。挂机期间的回复不会在下一通电话重播。
- `data/tts/` 为生成的 8k 单声道 PCM16 临时音频，正常播报后删除。测试或异常退出可能留下文件。

## 六、常见问题

| 现象 | 处理步骤 |
| --- | --- |
| 提示连接不到网页或找不到对话 | 确认 DSH 服务在运行，用 Edge 打开已有对话；只保留一个目标标签页，然后运行 `diagnose.cmd` |
| 弹出 Playwright Welcome 连接页 | 允许连接；如本地扩展令牌已失效，更新 `data/browser-extension-token.txt` |
| 提示 SIP/RTP 端口被占用 | 停止 ai-autoprint 电话服务，并确认没有重复启动本程序 |
| 提示网卡 IP 无效或无法绑定地址 | 确认电脑有 `192.168.0.1` 地址；如现场地址已变化，修改 `phone.local_address` 并同步 HT802 SIP 设置 |
| 摘机后没有提示音 | 先确认窗口显示“电话监听就绪”，再检查 HT802 接线、电源、SIP Server 和防火墙 |
| 说话后网页没有新增消息 | 查看启动窗口；确认网页无草稿、引用或附件；若没有触发收音，可适当降低 `phone.vad_rms` 后重启 |
| 腾讯云报 `4008` | 表示音频上传超时。2026-10-27 已修复“网页轮询误关闭正在识别的收音”问题；关闭旧程序窗口再重新启动以加载修复。若仍发生，检查电话是否持续传入音频；该错误本身不是密钥或套餐错误 |
| 一句话中间经常提前发送 | 将 `phone.silence_ms` 由 `450` 调至 `600`，必要时也增大 `long_silence_ms`，保存并重启 |
| 网页可能已经发送，但程序显示未确认 | 先看网页，避免手动重复发送；必要时查看 `data/pending-input.json`，处理后按座机 `#` 恢复收音 |
| 网页有回答，听筒没有声音 | 先检查窗口是否报告 TTS 错误，运行下方 `--test-tts`，再查看 `data/tts-worker.log`；合成正常后继续检查电话音频链路 |
| 想更换 AI 对话 | 挂机、按 `Ctrl+C` 退出，切换网页对话后重新启动 |

## 七、分项诊断与测试

在本目录 PowerShell 中执行：

```powershell
.\start.cmd --doctor                  # 路径、配置和凭据存在性
.\start.cmd --check-browser           # 实连网页，只读，不发送
.\start.cmd --test-asr                # 腾讯云鉴权和一秒静音识别，会调用云服务
.\start.cmd --test-tts                # 合成一句中文，保存 PCM，不向座机播放
```

日志：`data/phone-chat.log`、`data/phone-bridge.log`、`data/tts-worker.log`。密钥文件和本地令牌均在 `.gitignore` 中，请勿公开。

当前启动复用 ai-autoprint 的 Python 与 Node 可执行文件。要使用独立 Python 环境，执行 `powershell -ExecutionPolicy Bypass -File .\setup.ps1`，安装后自动更新配置；Node 路径可改为其他已安装 Node。TTS 始终使用其安装目录自己的环境。

HT802 保持既有设置：Primary SIP Server `192.168.0.1:5090`、关闭 SIP Registration、UDP、PCMU 优先、RFC2833 DTMF、摘机自动拨号 263。更改本机 SIP 地址/端口时也要同步设备设置。原防火墙规则若已允许相同 Node 程序和端口可直接复用；否则以管理员运行本目录 `firewall.ps1`，仅允许所配置 HT802 来源。

## 八、给后续 Agent：绑定页面的模块、参数与修改入口

项目根目录：`C:\Users\Administrator\Desktop\agent-langline\phone-chat`。网站收发模块完全不导入 ASR、电话或 TTS。

| 要修改的内容 | 文件和入口 |
| --- | --- |
| 把 ASR 最终文字注入网页 | `adapters/dsh_web.py` → `DshWebAdapter.send(text)`；执行填入、单次点击、确认新增用户消息 |
| 获取网页内用户输入与 AI 回答 | `adapters/dsh_web.py` → `snapshot()`，实际 DOM 提取在 `adapters/dsh_page_state.js` |
| 选择和固定对话页面 | `adapters/dsh_web.py` → `connect()`、`run()`；校验网页 origin 和 `data-conversation-session` |
| 修改独立文字进程与输出事件 | `text_gateway.py` → `TextGateway.send()`、`poll()`；输出 `user_text` 和 `assistant_text` |
| 新增其他网站的适配器 | 实现 `adapters/base.py` 的 `TextAdapter`，在 `adapters/__init__.py` 的 `create_adapter()` 注册 |
| 更改通用浏览器连接方式 | `browser_mcp.py`；只负责 Playwright MCP 通信，不处理网站 DOM |
| 网页文字如何交给音频链路 | `app.py` → `finish_utterance()`、`watch_page()`、`speak()` |
| TTS 推理后端或声音 | `tts_worker.py` 的 `load()` / `generate()`，以及 `config.json` 的 `tts` 节 |

以下是 `config.json` 中当前实际绑定值，简单的页面版本变化可先修改这些选择器：

```json
{
  "browser": {
    "adapter": "dsh_web",
    "url": "http://127.0.0.1:3080",
    "session_id": "",
    "editor_selector": "[data-composer-input][contenteditable=\"true\"]",
    "send_selector": "[data-composer-card] button[aria-label=\"发送消息\"], [data-composer-card] button[aria-label=\"Send message\"]",
    "user_selector": "[data-chat-flow-kind=\"user\"]",
    "assistant_selector": "[data-chat-flow-kind=\"assistant-step\"]",
    "busy_selector": "[data-chat-running], [data-streaming=\"true\"], [data-composer-card] button[aria-label=\"停止生成\"], [data-composer-card] button[aria-label=\"Stop generating\"]",
    "poll_seconds": 0.2,
    "stable_seconds": 0.2,
    "extension_token_file": "data/browser-extension-token.txt"
  }
}
```

`url` 当前按 origin 匹配，填写路径并不能区分同站多个对话。`session_id` 留空表示启动时绑定唯一打开的已有对话；要固定绑定，运行 `diagnose.cmd` 查看会话 ID，再填入此字段。不要在 Agent 修改时把当前示例会话 ID写死为所有用户的会话。

另有一些 DSH 专用属性写在适配器代码中，更换站点时也要处理：会话容器 `[data-conversation-content]`、会话 ID `data-conversation-session`、消息 ID `data-chat-node-key`、轮次 `data-chat-turn`、用户正文 `[data-message-bubble]`。AI 的 `data-chat-group-part="reasoning"`、`data-turn-process-member`、`[data-step-process]`、`[data-variant="think"]` 等被排除，不能当成最终回答。完整站点迁移应新增适配器，而不只是替换配置中的输入框选择器。

修改后的验证顺序：先运行 `text-web.cmd --snapshot` 只读检查，再在测试对话发送一句文字，确认 `send_result.accepted=true`、`user_text` 与 `assistant_text` 的 `session/turn` 对应，最后测试草稿保护和切换会话拒绝。接口和订阅示例见 [TEXT_API.md](TEXT_API.md)。

## 九、联网调研依据与第三方代码

电话协议和腾讯云适配器复制自本机 `ai-autoprint`，分别保留 `sip/LICENSE`（MIT）和 `vendor/tencent_speech/LICENSE`（Apache 2.0）。DSH 页面标记根据同级 `deepseek-harness` 当前源码实现。

CUDA Graph 加速代码随项目存放在 `vendor/faster-qwen3-tts-0.2.6`，保留其 MIT 许可。它复用 `D:\AI\Qwen3-TTS` 的模型与 Python 环境，未升级或覆盖原环境中的依赖。固定版本、来源和校验值见该目录的 `SOURCE.md`。

- [Playwright 官方：连接现有浏览器扩展](https://playwright.dev/mcp/configuration/browser-extension)
- [腾讯云实时识别 V2：音频与 input_sample_rate 参数](https://cloud.tencent.com/document/product/1093/131127)
- [腾讯云 V2 分句策略：0 最小语义短句、1 段落](https://cloud.tencent.com/document/product/1093/131127)：云端实时分句与本地是否结束用户轮次是两个不同层次；此项目保留策略 0。
- [Silero VAD 原始实现](https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py)：参考其独立起止门限、静音时长、前后保留音频及长语段切分思路。本项目采用轻量能量检测，并未声称已安装 Silero 模型。
- [Qwen 官方音色与模型说明](https://github.com/QwenLM/Qwen3-TTS)：Vivian 为明亮女声，Serena 为温柔女声；0.6B 不支持相同的指令控制，因此本次保留 1.7B。
- [faster-qwen3-tts 加速实现与 Windows 支持](https://github.com/andimarafioti/faster-qwen3-tts)：采用其中的 CUDA Graph 推理路径，效果以本机实测为准。

自动测试：`python -m unittest discover -s tests -p "test_*.py" -v`，以及 `node --test tests/*.test.mjs`。浏览器测试在独立无头 Edge 环境中运行；电话测试只使用本机回环地址模拟 HT802。`tests/live_text_smoke.py` 会向真实绑定对话发送一条明确标注的测试消息，仅在需要实连发送验收时运行。

实际接通验收：摘机说一句话，检查网页新增用户消息、收到 AI 回复，并听到听筒播报；随后同一通话再说第二句。仅诊断通过不代表 HT802 实物收音与听筒已验收。

腾讯云 `4008` 含义参见[腾讯云官方常见问题](https://cloud.tencent.cn/document/faq/1093/35803)。修复及有声识别验证记录见 [VALIDATION.md](VALIDATION.md)。
