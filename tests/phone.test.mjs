import test from 'node:test';
import assert from 'node:assert/strict';
import dgram from 'node:dgram';
import {spawn} from 'node:child_process';
import {mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {makeRtp, encodeMuLaw, parseRtp, decodeMuLaw} from '../sip/phone-audio.mjs';
import readline from 'node:readline';
const root = fileURLToPath(new URL('..',import.meta.url));
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function bind() {
  const socket = dgram.createSocket('udp4');
  await new Promise(resolve=>socket.bind(0,'127.0.0.1',resolve));
  return socket;
}
async function freePort() { const socket=await bind();const port=socket.address().port;socket.close();return port; }
test('loopback HT802 call receives speech and plays converted audio over PCMU RTP', {timeout:15000}, async () => {
  const dir = mkdtempSync(join(tmpdir(),'dsh-phone-test-'));
  const sip = await bind(), rtp = await bind();
  const cfg = JSON.parse(readFileSync(resolve(root,'config.json'),'utf8').replace(/^\uFEFF/,''));
  Object.assign(cfg.phone,{local_address:'127.0.0.1',device_address:'127.0.0.1',
    sip_port:await freePort(),rtp_port:await freePort(),device_sip_port:sip.address().port});
  mkdirSync(join(dir,'data/tts'),{recursive:true});
  const configPath=join(dir,'config.json'); writeFileSync(configPath,JSON.stringify(cfg));
  const child=spawn(process.execPath,[resolve(root,'sip/bridge.mjs'),configPath],{stdio:['pipe','pipe','pipe']});
  const events=[]; let stderr='';
  child.stderr.on('data',b=>stderr+=b);
  const lines=readline.createInterface({input:child.stdout});
  lines.on('line',line=>events.push(JSON.parse(line)));
  const wait=async kind=>{
    const deadline=Date.now()+5000;
    while(Date.now()<deadline){const item=events.find(e=>e.event===kind);if(item)return item;await sleep(10);}
    throw new Error('Timed out: '+kind+' '+stderr+' '+JSON.stringify(events));
  };
  const send=value=>child.stdin.write(JSON.stringify(value)+'\n');
  const callId='loopback-test@localhost';
  function signal(method,body='') {
    const message=`${method} sip:263@127.0.0.1 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:${sip.address().port};branch=z9hG4bKtest\r\nFrom: <sip:redline@127.0.0.1>;tag=test\r\nTo: <sip:263@127.0.0.1>\r\nCall-ID: ${callId}\r\nCSeq: ${method==='BYE'?2:1} ${method}\r\nContact: <sip:redline@127.0.0.1:${sip.address().port}>\r\nContent-Type: application/sdp\r\nContent-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`;
    sip.send(Buffer.from(message),cfg.phone.sip_port,'127.0.0.1');
  }
  let heard=false;
  rtp.on('message',data=>{
    const packet=parseRtp(data);
    if(packet?.payloadType===0 && [...packet.payload].some(b=>Math.abs(decodeMuLaw(b))>900))heard=true;
  });
  try {
    await wait('listening');send({command:'ready',value:true});await sleep(30);
    signal('INVITE',`v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio ${rtp.address().port} RTP/AVP 0 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\n`);
    await sleep(50);signal('ACK');await wait('connected');await sleep(230);
    send({command:'listen',call_id:callId,value:true});await sleep(20);
    for(let seq=0;seq<80;seq++) {
      const payload=Buffer.from(Array.from({length:160},(_,i)=>seq<20?encodeMuLaw(2000*Math.sin(2*Math.PI*700*(seq*160+i)/8000)):255));
      rtp.send(makeRtp(payload,seq,seq*160,1234),cfg.phone.rtp_port,'127.0.0.1');await sleep(20);
    }
    const ended=await wait('speech_end');assert.equal(ended.valid,true);
    const pcmEvents=events.filter(e=>e.event==='audio');assert.ok(pcmEvents.length>2);
    assert.equal(pcmEvents[0].call_id,callId);
    assert.ok(Buffer.from(pcmEvents[0].pcm,'base64').length<=3200);
    const pcm=Buffer.alloc(3200);for(let i=0;i<pcm.length;i+=2)pcm.writeInt16LE(2000,i);
    const path=join(dir,'data/tts/play.pcm');writeFileSync(path,pcm);heard=false;
    send({command:'play',call_id:callId,path,request_id:'play-1'});
    const played=await wait('played');assert.equal(played.request_id,'play-1');assert.equal(heard,true);
    signal('BYE');assert.equal((await wait('ended')).reason,'hangup');
  } finally {
    child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));
    sip.close();rtp.close();lines.close();rmSync(dir,{recursive:true,force:true});
  }
});
