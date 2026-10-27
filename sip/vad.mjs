// Original PCM stays unchanged; filtered energy is used only for endpointing.
export class Segmenter {
  constructor(options, emit) {
    this.options = options; this.emit = emit;
    this.noise = []; this.noiseMs = 0; this.previousInput = 0; this.previousOutput = 0;
    this.reset();
  }
  reset() {
    this.ring = []; this.active = false; this.duration = 0; this.voiced = 0;
    this.silent = 0; this.triggerMs = 0; this.pending = Buffer.alloc(0);
  }
  clearNoise() { this.noise = []; this.noiseMs = 0; this.previousInput = 0; this.previousOutput = 0; }
  level(pcm) {
    let energy = 0;
    const hz = this.options.vad_high_pass_hz ?? 0;
    const alpha = hz ? 1 / (1 + 2 * Math.PI * hz / 8000) : 0;
    for (let i = 0; i < pcm.length; i += 2) {
      const input = pcm.readInt16LE(i);
      const value = hz ? alpha * (this.previousOutput + input - this.previousInput) : input;
      this.previousInput = input; this.previousOutput = value;
      energy += value * value;
    }
    return Math.sqrt(energy / (pcm.length / 2));
  }
  rememberNoise(rms, ms) {
    this.noise.push({rms, ms}); this.noiseMs += ms;
    while (this.noise.length > 1 && this.noiseMs > (this.options.noise_window_ms ?? 2000)) this.noiseMs -= this.noise.shift().ms;
  }
  thresholds() {
    const levels = this.noise.map(n => n.rms).sort((a,b) => a-b);
    const noise = levels.length ? Math.min(this.options.noise_max_rms ?? 1200, levels[Math.floor((levels.length-1) * .2)]) : 0;
    const adaptive = this.options.noise_multiplier ?? 0;
    return {noise, start:Math.max(this.options.vad_rms, noise * adaptive),
      end:adaptive ? Math.max(this.options.vad_rms * .7, noise * (this.options.noise_end_multiplier ?? 1.5)) : this.options.vad_rms};
  }
  observe(pcm) { if (pcm.length) this.rememberNoise(this.level(pcm), pcm.length / 16); }
  push(pcm) {
    if (!pcm.length) return;
    const ms = pcm.length / 16;
    const rms = this.level(pcm);
    const threshold = this.active ? this.activeThreshold : this.thresholds();
    const loud = rms >= (this.active ? threshold.end : threshold.start);
    if (!this.active) {
      this.ring.push(pcm);
      const keep = (this.options.pre_roll_ms + (this.options.start_speech_ms ?? 0) + ms) * 16;
      while (this.ring.reduce((n,p) => n+p.length,0) > keep) this.ring.shift();
      this.triggerMs = loud ? this.triggerMs + ms : 0;
      if (!loud) this.rememberNoise(rms, ms);
      if (!loud || this.triggerMs < (this.options.start_speech_ms ?? 0)) return;
      this.active = true; this.activeThreshold = threshold;
      this.voiced = Math.max(0, this.triggerMs-ms); this.duration = this.voiced;
      this.emit('speech_start', {rms:Math.round(rms), noise_rms:Math.round(threshold.noise),
        start_threshold:Math.round(threshold.start), end_threshold:Math.round(threshold.end)});
      this.pending = Buffer.concat(this.ring); this.ring = [];
    } else this.pending = Buffer.concat([this.pending, pcm]);
    this.duration += ms;
    if (loud) { this.voiced += ms; this.silent = 0; } else this.silent += ms;
    while (this.pending.length >= 3200) {
      this.emit('audio', {pcm:this.pending.subarray(0, 3200).toString('base64')});
      this.pending = this.pending.subarray(3200);
    }
    const limit = this.duration >= this.options.max_utterance_seconds * 1000;
    const silenceTarget = this.options.long_utterance_ms && this.duration >= this.options.long_utterance_ms
      ? (this.options.long_silence_ms ?? this.options.silence_ms) : this.options.silence_ms;
    if (this.silent >= silenceTarget || limit) {
      if (this.pending.length) this.emit('audio', {pcm:this.pending.toString('base64')});
      this.emit('speech_end', {valid:this.voiced >= this.options.min_speech_ms,
        reason:limit ? 'duration_limit' : 'silence', speech_ms:this.voiced, silence_ms:this.silent});
      this.reset();
      return true;
    }
  }
}
