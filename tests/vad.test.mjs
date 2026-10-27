import test from 'node:test';
import assert from 'node:assert/strict';
import {Segmenter} from '../sip/vad.mjs';
const opts = {vad_rms:100,silence_ms:1000,min_speech_ms:240,pre_roll_ms:300,max_utterance_seconds:25};
const frame = sample => { const pcm=Buffer.alloc(320); for(let i=0;i<320;i+=2)pcm.writeInt16LE(sample,i); return pcm; };
test('silence does not start ASR; speech plus pause ends a turn before hangup', () => {
  const events=[]; const vad=new Segmenter(opts,(event,extra)=>events.push({event,...extra}));
  for(let i=0;i<30;i++)vad.push(frame(0));
  assert.equal(events.length,0);
  for(let i=0;i<20;i++)vad.push(frame(1000));
  for(let i=0;i<50;i++)vad.push(frame(0));
  assert.equal(events[0].event,'speech_start');
  assert.equal(events.at(-1).event,'speech_end');
  assert.equal(events.at(-1).valid,true);
  const bytes=events.filter(e=>e.event==='audio').reduce((n,e)=>n+Buffer.from(e.pcm,'base64').length,0);
  assert.equal(bytes, (300+400+1000)*16);
});
test('a brief click is not a valid caller utterance', () => {
  const events=[]; const vad=new Segmenter(opts,(event,extra)=>events.push({event,...extra}));
  vad.push(frame(5000)); for(let i=0;i<50;i++)vad.push(frame(0));
  assert.equal(events.at(-1).valid,false);
});

function acousticFrame(frameIndex, speech=false) {
  const pcm=Buffer.alloc(320);
  for(let i=0;i<160;i++) {
    const t=(frameIndex*160+i)/8000;
    const value=450*Math.sin(2*Math.PI*120*t)+(speech?2300*Math.sin(2*Math.PI*700*t):0);
    pcm.writeInt16LE(Math.round(value),i*2);
  }
  return pcm;
}
const noisyOpts={...opts,vad_rms:300,silence_ms:450,min_speech_ms:160,pre_roll_ms:160,
  start_speech_ms:60,noise_multiplier:2.6,noise_end_multiplier:1.5,
  noise_window_ms:2000,noise_max_rms:1200,vad_high_pass_hz:150};
test('fan noise neither starts a turn nor prevents 450ms endpoint after speech', () => {
  const events=[];const vad=new Segmenter(noisyOpts,(event,extra)=>events.push({event,...extra}));
  let seq=0;for(let i=0;i<40;i++)vad.observe(acousticFrame(seq++));
  for(let i=0;i<50;i++)vad.push(acousticFrame(seq++));
  assert.equal(events.length,0);
  for(let i=0;i<25;i++)vad.push(acousticFrame(seq++,true));
  for(let i=0;i<23;i++)vad.push(acousticFrame(seq++));
  assert.equal(events[0].event,'speech_start');
  assert.equal(events.at(-1).event,'speech_end');
  assert.equal(events.at(-1).valid,true);
  assert.ok(events.at(-1).silence_ms<=460);
  assert.equal(events.at(-1).reason,'silence');
});
test('short within-sentence pause does not split; long speech uses natural pause', () => {
  const events=[];const vad=new Segmenter({...noisyOpts,long_utterance_ms:1200,long_silence_ms:300},(event,extra)=>events.push({event,...extra}));
  let seq=0;for(let i=0;i<30;i++)vad.observe(acousticFrame(seq++));
  for(let i=0;i<30;i++)vad.push(acousticFrame(seq++,true));
  for(let i=0;i<10;i++)vad.push(acousticFrame(seq++));
  assert.equal(events.some(e=>e.event==='speech_end'),false);
  for(let i=0;i<35;i++)vad.push(acousticFrame(seq++,true));
  for(let i=0;i<15;i++)vad.push(acousticFrame(seq++));
  assert.equal(events.at(-1).event,'speech_end');
  assert.equal(events.at(-1).silence_ms,300);
});
