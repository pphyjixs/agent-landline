# faster-qwen3-tts 0.2.6

Upstream: https://github.com/andimarafioti/faster-qwen3-tts

Pinned release: 0.2.6, upstream tag commit `5ae964a39fadec39141db779f5c5e4768ddd2b22`.

Source: PyPI wheel `faster_qwen3_tts-0.2.6-py3-none-any.whl`, unpacked without installing or changing the existing TTS environment.

SHA256: `3881a41dc189f0a6e93fa047f376deffeb2fa84e888e7d570f79b3e2267765cc`.

License: MIT, retained under `faster_qwen3_tts-0.2.6.dist-info/licenses/LICENSE`.

This version supports the existing Torch 2.9.1 / Transformers 4.57.3 / qwen-tts installation. Later releases require different dependencies, so updates must be validated before changing this pin. The app adds this directory to the worker's Python import path only when `tts.backend=cuda_graph`; model files remain in D:\AI\Qwen3-TTS.
