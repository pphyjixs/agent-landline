// Local-only HT802 simulator for the real streaming ASR regression smoke.
import dgram from 'node:dgram';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {makeRtp, encodeMuLaw} from '../sip/phone-audio.mjs';
const cfg=JSON.parse(readFileSync(process.argv[2],'utf8'));
if(cfg.phone.local_address!=='127.0.0.1'||cfg.phone.device_address!=='127.0.0.1')throw new Error('Loopback only');
const pcm=readFileSync(process.argv[3]);
const noiseAmplitude=Number(process.argv[4]||0);
const sip=dgram.createSocket('udp4'),rtp=dgram.createSocket('udp4');
const callId=randomUUID()+'@localhost';
let active=false,timer,stopping=false;
await Promise.all([
  new Promise(resolve=>sip.bind(cfg.phone.device_sip_port,'127.0.0.1',resolve)),
  new Promise(resolve=>rtp.bind(0,'127.0.0.1',resolve)),
]);
const body=`v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio ${rtp.address().port} RTP/AVP 0 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\n`;
function signal(method){
  const sdp=method==='INVITE'?body:'';
  sip.send(Buffer.from(`${method} sip:263@127.0.0.1 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:${cfg.phone.device_sip_port};branch=z9hG4bKtest\r\nFrom: <sip:redline@127.0.0.1>;tag=test\r\nTo: <sip:263@127.0.0.1>\r\nCall-ID: ${callId}\r\nCSeq: ${method==='BYE'?2:1} ${method}\r\nContact: <sip:redline@127.0.0.1:${cfg.phone.device_sip_port}>\r\nContent-Type: application/sdp\r\nContent-Length: ${Buffer.byteLength(sdp)}\r\n\r\n${sdp}`),cfg.phone.sip_port,'127.0.0.1');
}
sip.on('message',packet=>{
  if(!packet.toString().startsWith('SIP/2.0 200')||active)return;
  active=true;signal('ACK');
  let seq=0,offset=0;
  timer=setInterval(()=>{
    const payload=Buffer.alloc(160,255);
    for(let i=0;i<160;i++){
      let sample=0;
      if(seq>=60&&offset<pcm.length){sample=pcm.readInt16LE(offset);offset+=2;}
      sample+=noiseAmplitude*Math.sin(2*Math.PI*120*(seq*160+i)/8000);
      payload[i]=encodeMuLaw(sample);
    }
    rtp.send(makeRtp(payload,seq,seq*160,1234),cfg.phone.rtp_port,'127.0.0.1');seq++;
  },20);
});
function stop(){
  if(stopping)return;stopping=true;clearInterval(timer);clearTimeout(timeout);
  if(active)signal('BYE');
  setTimeout(()=>{sip.close();rtp.close();},100);
}
const timeout=setTimeout(stop,45000);
process.stdin.resume();process.stdin.on('end',stop);
signal('INVITE');
