"""Silent, offline WebRTC transport benchmark. No Dan session or paid API.

Uses two headless Chromium peers and a local UDP relay. Results describe Chromium
transport only, NOT Android audio hardware or ChatGPT/OpenAI service behavior.
"""
import argparse
import asyncio
import base64
import hashlib
import ipaddress
import json
import random
import socket
import time
from pathlib import Path

from playwright.async_api import async_playwright


class Relay(asyncio.DatagramProtocol):
    def __init__(self, remote, profile, seed):
        self.remote, self.profile = remote, profile
        self.rng = random.Random(seed)
        self.client = None
        self.active = False
        self.next_at = {'up': 0, 'down': 0}
        self.pending = set()
        self.counts = {k: 0 for k in ('up', 'down', 'bytes', 'loss_drop', 'queue_drop', 'forwarded')}
        self.max_queue_ms = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if addr == self.remote:
            direction, target = 'down', self.client
        elif ipaddress.ip_address(addr[0]).is_loopback and self.client in (None, addr):
            self.client = addr
            direction, target = 'up', self.remote
        else:
            return
        if target is None:
            return
        self.counts[direction] += 1
        self.counts['bytes'] += len(data)
        loss, delay, jitter, kbps = self.profile if self.active else (0, 0, 0, 0)
        if self.rng.random() < loss:
            self.counts['loss_drop'] += 1
            return
        now = time.monotonic()
        lag = max(0, delay + self.rng.uniform(-jitter, jitter))
        if kbps:
            finish = max(now, self.next_at[direction]) + len(data) * 8 / (kbps * 1000)
            if finish - now > 0.5:
                self.counts['queue_drop'] += 1
                return
            self.next_at[direction] = finish
            self.max_queue_ms = max(self.max_queue_ms, (finish - now) * 1000)
            lag += finish - now
        def send():
            self.pending.discard(handle)
            if not self.transport.is_closing():
                self.transport.sendto(data, target)
                self.counts['forwarded'] += 1
        handle = asyncio.get_running_loop().call_later(lag, send)
        self.pending.add(handle)

    def close(self):
        for handle in self.pending:
            handle.cancel()
        self.transport.close()


async def rewrite(sdp, profile, seed):
    # Never forward traffic to a public server or an unrelated LAN host.
    own = {'127.0.0.1'} | {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    lines, relays = [], []
    for line in sdp.splitlines():
        if line.startswith('a=candidate:'):
            fields = line.split()
            if fields[2].lower() != 'udp' or fields[4] not in own:
                continue
            relay = Relay((fields[4], int(fields[5])), profile, seed + len(relays))
            await asyncio.get_running_loop().create_datagram_endpoint(lambda: relay, local_addr=('0.0.0.0', 0))
            fields[4:6] = ['127.0.0.1', str(relay.transport.get_extra_info('sockname')[1])]
            line = ' '.join(fields)
            relays.append(relay)
        lines.append(line)
    if not relays:
        raise RuntimeError('No local IPv4 UDP candidates; refusing an unshaped test')
    return '\r\n'.join(lines) + '\r\n', relays


SETUP = r"""async ({wav, nack}) => {
 const ctx = new AudioContext({sampleRate:48000}); await ctx.resume();
 const decoded = await ctx.decodeAudioData(Uint8Array.from(atob(wav),c=>c.charCodeAt(0)).buffer);
 const dest = ctx.createMediaStreamDestination();
 const source = ctx.createBufferSource(); source.buffer=decoded; source.loop=true; source.connect(dest);
 const tx = new RTCPeerConnection({iceServers:[]});
 const rx = new RTCPeerConnection({iceServers:[]});
 const sender = tx.addTrack(dest.stream.getAudioTracks()[0],dest.stream);
 // Force identical Opus negotiation rather than allow a different codec in one case.
 const codecs=RTCRtpSender.getCapabilities('audio').codecs.filter(c=>c.mimeType==='audio/opus');
 tx.getTransceivers()[0].setCodecPreferences(codecs);
 let sink, analyser;
 rx.ontrack=e=>{
   sink=ctx.createMediaStreamSource(new MediaStream([e.track]));
   analyser=ctx.createAnalyser(); sink.connect(analyser);
   // Chromium is globally muted, but the graph must pull real PCM. A zero-gain
   // branch may be optimized away, producing misleading zero concealment stats.
   analyser.connect(ctx.destination);
   const audio=document.createElement('audio');audio.srcObject=new MediaStream([e.track]);
   document.body.appendChild(audio);audio.play();
 };
 const gather=pc=>new Promise(resolve=>{
   if(pc.iceGatheringState==='complete') return resolve();
   pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete')resolve();});
 });
 let offer=await tx.createOffer();
 if(nack){const pt=offer.sdp.match(/a=rtpmap:(\d+) opus/)[1];offer.sdp=offer.sdp.replace('a=rtpmap:'+pt+' opus/48000/2','a=rtpmap:'+pt+' opus/48000/2\r\na=rtcp-fb:'+pt+' nack');}
 await tx.setLocalDescription(offer);await gather(tx);
 // Removing the offer candidates prevents the answer peer opening a direct route.
 const stripped=tx.localDescription.sdp.split('\r\n').filter(l=>!l.startsWith('a=candidate:')).join('\r\n');
 await rx.setRemoteDescription({type:'offer',sdp:stripped});
 await rx.setLocalDescription(await rx.createAnswer());await gather(rx);
 window.bench={tx,rx,ctx,source,sender};
 window.snapshot=async()=>{
   const stats=Array.from((await rx.getStats()).values());
   const txstats=Array.from((await tx.getStats()).values());
   return {rx:stats.filter(s=>['inbound-rtp','candidate-pair','local-candidate','remote-candidate','transport'].includes(s.type)),
     tx:txstats.filter(s=>['outbound-rtp','candidate-pair','local-candidate','remote-candidate','transport'].includes(s.type))};
 };
 return rx.localDescription.sdp;
}"""


async def run(args):
    wav = Path(args.wav).read_bytes()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    profiles = {'clean': (0,0,0,0), 'loss': (.1,0,0,0), 'jitter': (0,.12,.08,0),
                'rate64': (0,0,0,64), 'combined128': (.1,.12,.08,128), 'combined64': (.1,.12,.08,64)}
    async with async_playwright() as pw:
        for case in args.cases.split(','):
            for nack in ((True,) if args.nack_only else (False, True)):
                relays = []
                flags = ['--mute-audio', '--autoplay-policy=no-user-gesture-required', '--disable-features=WebRtcHideLocalIpsWithMdns']
                if args.bounded and nack:
                    flags.append('--force-fieldtrials=WebRTC-Audio-NetEqDelayManagerConfig/quantile:0.99,use_reorder_optimizer:false,resample_interval_ms:100/WebRTC-Audio-NetEqNackTrackerConfig/never_nack_multiple_times:true/')
                elif args.bounded_only and nack:
                    flags.append('--force-fieldtrials=WebRTC-Audio-NetEqNackTrackerConfig/never_nack_multiple_times:true/')
                browser = await pw.chromium.launch(headless=True, args=flags)
                try:
                    page = await browser.new_page()
                    sdp = await asyncio.wait_for(page.evaluate(SETUP, {'wav':base64.b64encode(wav).decode(), 'nack':nack}), 20)
                    sdp, relays = await rewrite(sdp, profiles[case], args.seed)
                    await page.evaluate("sdp=>bench.tx.setRemoteDescription({type:'answer',sdp})", sdp)
                    await page.wait_for_function("bench.tx.connectionState==='connected' && bench.rx.connectionState==='connected'", timeout=15000)
                    await page.evaluate('bench.source.start()')
                    await asyncio.sleep(2)
                    before = await page.evaluate('snapshot()')
                    # The selected sender remote address MUST be one of the shaper ports.
                    ports = {r.transport.get_extra_info('sockname')[1] for r in relays}
                    transport = next(s for s in before['tx'] if s['type']=='transport')
                    pair = next(s for s in before['tx'] if s['id']==transport['selectedCandidatePairId'])
                    remote = next(s for s in before['tx'] if s['id']==pair['remoteCandidateId'])
                    assert remote['port'] in ports, 'ICE bypassed the shaper'
                    for relay in relays: relay.active = True
                    await asyncio.sleep(args.seconds)
                    after = await page.evaluate('snapshot()')
                    def inbound(snapshot): return next(s for s in snapshot['rx'] if s['type']=='inbound-rtp')
                    a, b = inbound(before), inbound(after)
                    assert b.get('totalSamplesReceived',0) > a.get('totalSamplesReceived',0), 'No decoded audio; invalid trial'
                    assert b.get('totalAudioEnergy',0) > a.get('totalAudioEnergy',0), 'No non-silent audio; invalid trial'
                    keys = ['packetsLost','packetsReceived','concealedSamples','silentConcealedSamples','totalSamplesReceived','jitterBufferDelay','jitterBufferEmittedCount','nackCount']
                    delta = {k:b.get(k,0)-a.get(k,0) for k in keys}
                    result = {'case':case,'nack':nack,'requestedBrowserFlags':flags,'browser':browser.version,'seconds':args.seconds,'seed':args.seed,
                              'wavSha256':hashlib.sha256(wav).hexdigest(),'profile':profiles[case], 'selectedRemote':remote,
                              'delta':delta,'before':before,'after':after,'relays':[dict(r.counts,maxQueueMs=r.max_queue_ms) for r in relays]}
                    (output/f'{case}-nack{int(nack)}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                    print(json.dumps({'case':case,'nack':nack,'concealedPercent':round(100*delta['concealedSamples']/max(1,delta['totalSamplesReceived']),2),
                                      'bufferMs':round(1000*delta['jitterBufferDelay']/max(1,delta['jitterBufferEmittedCount']),1),'nackCount':delta['nackCount'],
                                      'drops':sum(r.counts['loss_drop']+r.counts['queue_drop'] for r in relays)}),flush=True)
                finally:
                    for relay in relays: relay.close()
                    await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wav',required=True)
    parser.add_argument('--output',default='.tmp/voice-transport-offline')
    parser.add_argument('--cases',default='clean,loss,jitter,rate64,combined128,combined64')
    parser.add_argument('--seconds',type=float,default=20)
    parser.add_argument('--seed',type=int,default=20260920)
    parser.add_argument('--bounded',action='store_true',help='Request the Android candidate field trials in Chromium; not proof of Android behavior')
    parser.add_argument('--nack-only',action='store_true')
    parser.add_argument('--bounded-only',action='store_true',help='Limit retransmission without changing the delay manager')
    asyncio.run(run(parser.parse_args()))
