# Tencent Cloud Speech SDK (Python)

Source: https://github.com/TencentCloud/tencentcloud-speech-sdk-python
Pinned revision: d362182909aaf25f95cd93449c4aeae8e0b449bf

Only `asr/speech_recognizer.py`, `asr/realtime_recognizer_v2.py` and `common/credential.py` are included, with the
upstream LICENSE. Local modifications: replace the global `common.log`
import with a disabled SDK logger (the adapter reports sanitized errors), and set
STARTED before launching the WebSocket thread to avoid an open/start race.

V2 also uses the disabled logger. Its local fixes URL-encode query values (Chinese
hotwords), bound connect/first-response waits, expose the connection for cancellation,
report handshake errors via the listener, mark EOF closed and deliver sentence data
included in the final message before signaling completion. The adapter selects the
official V2 SDK for `16k_zh_en_2.0` / `16k_zh_en_speaker_2.0` and normalizes its
`sentences.sentence_list` callbacks. Speaker separation stays off by default.

The application uses the SDK's signing, connection, callbacks and binary writes.
The adapter provides bounded connection/finalization, cancellation and audio pacing.
It uses websocket-client 1.8.0, verified with a local WebSocket protocol fixture;
upstream's legacy README mentions 0.48. No generic cloud REST SDK is required.
