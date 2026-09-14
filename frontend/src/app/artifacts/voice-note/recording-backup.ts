// Durable recovery of recordings, scoped to the authenticated workspace and article.
function open():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('voice-note-recordings',1);r.onupgradeneeded=()=>r.result.createObjectStore('audio');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
export async function recordingBackup(key:string, value?:Blob|null):Promise<Blob|undefined>{
 const db=await open();return new Promise((resolve,reject)=>{const tx=db.transaction('audio',value===undefined?'readonly':'readwrite');const store=tx.objectStore('audio');const r=value===undefined?store.get(key):value===null?store.delete(key):store.put(value,key);tx.oncomplete=()=>{db.close();resolve(value===undefined?r.result:undefined);};tx.onerror=()=>{db.close();reject(tx.error);};tx.onabort=()=>{db.close();reject(tx.error);};});
}
