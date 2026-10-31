/** Consume only complete length-delimited JPEG frames, with bounded buffering. */
export async function readScreenFrames(
  body: ReadableStream<Uint8Array>, onFrame: (blob: Blob) => void,
) {
  const reader = body.getReader();
  let buffer = new Uint8Array(0);
  const decoder = new TextDecoder();
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      const next = new Uint8Array(buffer.length + value.length);
      next.set(buffer); next.set(value, buffer.length); buffer = next;
      if (buffer.length > 8 * 1024 * 1024) throw new Error('Screen frame too large');
      while (buffer.length) {
        let end = -1;
        for (let i=0;i+3<buffer.length;i++) {
          if (buffer[i]===13 && buffer[i+1]===10 && buffer[i+2]===13 && buffer[i+3]===10) {end=i;break;}
        }
        if (end<0) break;
        const header = decoder.decode(buffer.slice(0,end));
        const match = /Content-Length:\s*(\d+)/i.exec(header);
        const size = match ? Number(match[1]) : 0;
        if (!size || size>4*1024*1024 || !/Content-Type:\s*image\/jpeg/i.test(header)) throw new Error('Invalid screen frame');
        const start = end+4;
        if (buffer.length < start+size+2) break;
        onFrame(new Blob([buffer.slice(start,start+size)], {type:'image/jpeg'}));
        buffer = buffer.slice(start+size+2);
      }
    }
  } finally { await reader.cancel().catch(()=>{}); reader.releaseLock(); }
}
