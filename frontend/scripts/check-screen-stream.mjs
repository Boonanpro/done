import assert from 'node:assert/strict';
import {readScreenFrames} from '../src/components/voice/screen-stream.ts';
const encode=new TextEncoder();
const bytes=encode.encode('--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 3\r\n\r\none\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 3\r\n\r\ntwo\r\n');
for(const size of [1,7,64,1000]) {
 const found=[];
 await readScreenFrames(new ReadableStream({start(c){for(let i=0;i<bytes.length;i+=size)c.enqueue(bytes.slice(i,i+size));c.close();}}),b=>found.push(b));
 assert.deepEqual(await Promise.all(found.map(b=>b.text())),['one','two']);
}
await assert.rejects(readScreenFrames(new ReadableStream({start(c){c.enqueue(encode.encode('--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 9999999\r\n\r\n'));c.close();}}),()=>{}));
console.log('Frame fragmentation and size bounds passed');
