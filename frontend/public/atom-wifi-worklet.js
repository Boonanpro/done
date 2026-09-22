// Local PCM transport for the opt-in Atom Wi-Fi prototype, 48 kHz mono.
class AtomWifiMic extends AudioWorkletProcessor {
  constructor() {
    super(); this.queue=[];this.offset=0;this.samples=0;
    this.port.onmessage=e=>{
      const pcm=new Int16Array(e.data);this.queue.push(pcm);this.samples+=pcm.length;
      while(this.samples>9600&&this.queue.length>1){this.samples-=this.queue[0].length-this.offset;this.queue.shift();this.offset=0;}
    };
  }
  process(inputs,outputs) {
    const out=outputs[0][0];
    for(let i=0;i<out.length;i++) {
      if(!this.queue.length){out[i]=0;continue;}
      out[i]=this.queue[0][this.offset++]/32768;this.samples--;
      if(this.offset>=this.queue[0].length){this.queue.shift();this.offset=0;}
    }
    return true;
  }
}
class AtomWifiSpeaker extends AudioWorkletProcessor {
  constructor(){super();this.pcm=new Float32Array(480);this.index=0;this.gain=1;this.muted=false;
    this.port.onmessage=e=>{this.muted=e.data==='interrupt';this.index=0;};
  }
  process(inputs,outputs){
    const input=inputs[0]?.[0];
    for(const output of outputs[0]||[])output.fill(0);
    if(!input)return true;
    for(const v of input){
      this.pcm[this.index++]=this.muted?0:v*2;
      if(this.index===480){
        let peak=0;for(const x of this.pcm)peak=Math.max(peak,Math.abs(x));
        this.gain=Math.min(peak>.9?.9/peak:1,this.gain+.08);
        const packet=new Int16Array(480);
        for(let i=0;i<480;i++)packet[i]=Math.round(this.pcm[i]*this.gain*32767);
        this.port.postMessage(packet.buffer,[packet.buffer]);this.index=0;
      }
    }
    return true;
  }
}
registerProcessor('atom-wifi-mic',AtomWifiMic);
registerProcessor('atom-wifi-speaker',AtomWifiSpeaker);
