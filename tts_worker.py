"""Persistent Qwen inference process using D:\\AI\\Qwen3-TTS's Python environment."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    config_file = Path(sys.argv[1]).resolve()
    cfg = json.loads(config_file.read_text(encoding='utf-8-sig'))['tts']
    root = Path(cfg['root'])
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', HF_HOME=str(root / 'cache/huggingface'))
    sys.path.insert(0, str(root / 'source'))
    model = None
    def respond(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)

    def load():
        nonlocal model
        if model is not None:
            return
        import torch
        if cfg['device'].startswith('cuda') and not torch.cuda.is_available():
            raise RuntimeError('NVIDIA GPU 不可用')
        torch.set_num_threads(min(6, os.cpu_count() or 4))
        if cfg.get('backend','official') == 'cuda_graph':
            sys.path.insert(0,str(Path(__file__).resolve().parent / 'vendor/faster-qwen3-tts-0.2.6'))
            from faster_qwen3_tts import FasterQwen3TTS
            model = FasterQwen3TTS.from_pretrained(cfg['model_path'],device=cfg['device'],
                dtype=getattr(torch,cfg['dtype']),attn_implementation=cfg['attention'],
                max_seq_len=cfg.get('max_seq_len',1024))
            model._warmup(prefill_len=100)
        else:
            from qwen_tts import Qwen3TTSModel
            model = Qwen3TTSModel.from_pretrained(
                cfg['model_path'], device_map=cfg['device'], dtype=getattr(torch, cfg['dtype']),
                attn_implementation=cfg['attention'], local_files_only=True, low_cpu_mem_usage=True)

    def generate(text):
        import torch
        common = dict(text=text,language=cfg['language'],max_new_tokens=cfg['max_new_tokens'],
                      do_sample=cfg.get('do_sample',True))
        if cfg.get('backend','official') == 'official':
            common['subtalker_dosample'] = cfg.get('do_sample',True)
        with torch.inference_mode():
            if cfg['mode'] == 'custom_voice':
                return model.generate_custom_voice(**common,speaker=cfg['speaker'],instruct=cfg['instruct'])
            if cfg['mode'] == 'voice_design':
                return model.generate_voice_design(**common,instruct=cfg['instruct'])
            if cfg['mode'] == 'voice_clone':
                clone = dict(ref_audio=cfg['reference_audio'],ref_text=cfg['reference_text'] or '')
                clone['xvec_only' if cfg.get('backend','official') == 'cuda_graph' else 'x_vector_only_mode'] = not bool(cfg['reference_text'])
                return model.generate_voice_clone(**common,**clone)
            raise ValueError('tts.mode 必须是 custom_voice / voice_design / voice_clone')

    for line in sys.stdin:
        msg = {}
        try:
            msg = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                load()
                if msg['command'] == 'warmup':
                    if cfg.get('warmup_inference',False):
                        generate('你好。')
                    result = {'ready':True,'backend':cfg.get('backend','official')}
                else:
                    import numpy as np
                    import torch
                    from scipy.signal import resample_poly
                    from math import gcd
                    started = time.monotonic()
                    waves, sr = generate(msg['text'])
                    wave = np.asarray(waves[0], dtype=np.float32).reshape(-1)
                    if not wave.size or not np.isfinite(wave).all():
                        raise RuntimeError('TTS 返回空音频或无效音频')
                    divisor = gcd(int(sr), 8000)
                    wave = resample_poly(wave, 8000 // divisor, int(sr) // divisor)
                    pcm = (np.clip(wave, -1, 1) * 32767).astype('<i2')
                    target = config_file.parent / 'data/tts' / (msg['id'] + '.pcm')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(pcm.tobytes())
                    result = {'path':str(target), 'seconds':len(pcm) / 8000,
                              'synthesis_seconds':round(time.monotonic()-started,3),
                              'backend':cfg.get('backend','official')}
            respond({'id':msg['id'], **result})
        except Exception as error:
            # Full model diagnostics stay in the local worker log.
            import traceback
            traceback.print_exc(file=sys.stderr)
            respond({'id':msg.get('id'), 'error':type(error).__name__ + '：本地 TTS 失败，请查看 data/tts-worker.log'})


if __name__ == '__main__':
    main()
