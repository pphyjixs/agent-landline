import {PhoneSip} from './phone-sip.mjs';
import {decodeMuLaw, encodeMuLaw, tone} from './phone-audio.mjs';
import {Segmenter} from './vad.mjs';
import {readFileSync, realpathSync} from 'node:fs';
import {resolve, dirname, sep} from 'node:path';
import readline from 'node:readline';

const configFile = resolve(process.argv[2]);
const cfg = JSON.parse(readFileSync(configFile, 'utf8').replace(/^\uFEFF/, ''));
const opts = cfg.phone;
const phone = new PhoneSip({host:opts.local_address, peer:opts.device_address,
  port:opts.sip_port, peerPort:opts.device_sip_port, rtpPort:opts.rtp_port});
let stopping = false, ready = false, listening = false, lastAudio = Date.now(), noiseAfter = 0;
let utterance = 0;
const emit = (event, more = {}) => process.stdout.write(JSON.stringify({event, call_id:phone.call?.id || '', ...more}) + '\n');
const segmenter = new Segmenter(opts, (event, more) => {
  if (event === 'speech_start') utterance++;
  emit(event, {utterance, ...more});
});
const reset = () => { listening = false; segmenter.reset(); };
phone.allowIncoming = () => ready && !stopping;
phone.on('failure', error => { emit('fatal', {error:error.message}); stop(1); });
phone.on('connected', call => {
  clearTimeout(call.maxDuration);
  call.maxDuration = setTimeout(() => phone.hangup('duration_limit'), opts.max_call_seconds * 1000);
  reset(); segmenter.clearNoise(); lastAudio = Date.now(); noiseAfter = Date.now() + 400; emit('connected');
  phone.play(tone(660, .18)).catch(error => emit('error', {error:error.message}));
});
phone.on('audio', (payload) => {
  lastAudio = Date.now();
  const pcm = Buffer.alloc(payload.length * 2);
  for (let i = 0; i < payload.length; i++) pcm.writeInt16LE(decodeMuLaw(payload[i]), i * 2);
  if (!listening) {
    // Exclude playback and its echo from between-turn fan-noise calibration.
    if (phone.call?.playback) noiseAfter = Date.now() + opts.echo_guard_ms;
    else if (Date.now() >= noiseAfter) segmenter.observe(pcm);
    return;
  }
  if (segmenter.push(pcm)) listening = false;
});
phone.on('digit', digit => {
  if (digit === '#') { reset(); emit('resume_requested'); }
});
phone.on('ended', ({call, reason}) => { reset(); emit('ended', {call_id:call.id, reason}); });
const timer = setInterval(() => {
  if (phone.call?.connected && Date.now() - lastAudio > opts.media_timeout_seconds * 1000) phone.hangup('media_timeout');
}, 1000);
function stop(code = 0) {
  if (stopping) return;
  stopping = true; clearInterval(timer);
  phone.close(); process.exit(code);
}
const commands = readline.createInterface({input:process.stdin});
commands.on('line', async line => {
  let msg;
  try {
    msg = JSON.parse(line);
    if (msg.command === 'ready') { ready = Boolean(msg.value); return; }
    if (msg.command === 'stop') { stop(); return; }
    if (!phone.call?.connected || msg.call_id !== phone.call.id) {
      if (msg.request_id) emit('play_failed', {request_id:msg.request_id, error:'电话未接通或通话已变更'});
      return;
    }
    if (msg.command === 'listen') { reset(); listening = Boolean(msg.value); }
    if (msg.command === 'play') {
      reset();
      const allowed = realpathSync(resolve(dirname(configFile), 'data', 'tts')) + sep;
      const path = realpathSync(msg.path);
      if (!path.startsWith(allowed)) throw new Error('音频文件不在 data/tts 内');
      const pcm = readFileSync(path);
      if (!pcm.length || pcm.length % 2 || pcm.length > 8000 * 2 * 180) throw new Error('无效的 8k PCM16 音频');
      const ulaw = Buffer.alloc(pcm.length / 2);
      for (let i = 0; i < ulaw.length; i++) ulaw[i] = encodeMuLaw(pcm.readInt16LE(i * 2));
      const callId = phone.call.id;
      await phone.play(ulaw);
      emit('played', {call_id:callId, request_id:msg.request_id});
    }
  } catch (error) { emit(msg?.request_id ? 'play_failed' : 'error', {request_id:msg?.request_id, error:error.message}); }
});
commands.on('close', () => stop());
process.on('SIGINT', () => stop()); process.on('SIGTERM', () => stop());
try { await phone.start(); emit('listening', {address:phone.host, port:phone.port}); }
catch (error) { emit('fatal', {error:'SIP/RTP 启动失败，请检查网卡 IP 和端口占用：' + error.message}); stop(1); }
