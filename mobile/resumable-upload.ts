import {File} from 'expo-file-system';
import {fetch as nativeFetch} from 'expo/fetch';
import {ui} from './ui-language';

class TransferError extends Error { constructor(public status:number){super(String(status))} }
const sessions=new Map<string,string>();
export function uploadError(error:unknown):string {
 const status=error instanceof TransferError?error.status:0;
 if(status===401||status===403)return ui('Your session expired. Sign in again, then retry. Your attachment is still here.','ログインの有効期限が切れました。ログインし直して再送してください。添付は残っています。');
 if(status===413||status===422)return ui('This file is too large. You can send files up to 2 GB.','このファイルは大きすぎます。2GBまで送信できます。');
 if(status===415)return ui('This file format is not supported. Choose another file.','この形式は送信できません。別のファイルを選んでください。');
 if(status===400)return ui('Could not read this attachment. Please choose the file again.','添付を読み込めませんでした。ファイルを選び直してください。');
 if(status===507)return ui('Storage is full. Please try again later.','保存先の空き容量が不足しています。時間をおいて再送してください。');
 return ui('Upload interrupted. Check your connection and tap Send to resume. Your attachment is still here.','送信が中断されました。接続を確認して送信を押すと続きから再開します。添付は残っています。');
}
export async function uploadMedia(base:string,token:string,attachment:{uri:string;name:string;mime:string},onProgress?:(value:number)=>void,roomId?:string):Promise<any>{
 let file:File,size:number;
 try{file=new File(attachment.uri);size=file.size}catch{throw new TransferError(400)}
 if(size>2*1024*1024*1024)throw new TransferError(413);
 if(!size)throw new TransferError(400);
 const key=JSON.stringify([base,token,roomId,attachment.uri,size]);
 const endpoint=`${base}/api/v1/files/transfers`;
 const call=async(url:string,method='GET',body?:string|ArrayBuffer)=>{
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),120000);
  try{
   const response=await nativeFetch(url,{method,headers:{Authorization:`Bearer ${token}`,'Content-Type':typeof body==='string'?'application/json':'application/octet-stream'},body,signal:controller.signal});
   if(!response.ok)throw new TransferError(response.status);
   return await response.json();
  }finally{clearTimeout(timer)}
 };
 let id=sessions.get(key),state:any;
 if(id){try{state=await call(`${endpoint}/${id}`)}catch(e){if(e instanceof TransferError&&(e.status===404||e.status===410)){sessions.delete(key);id=undefined}else throw e}}
 if(!id){state=await call(endpoint,'POST',JSON.stringify({filename:attachment.name,size,content_type:attachment.mime,room_id:roomId}));id=state.id;sessions.set(key,id!)}
 if(state.result){onProgress?.(1);return state.result}
 const handle=file.open();
 let failures=0;
 try{
  while(state.offset<size){
   const offset=state.offset;
   handle.offset=offset;
   const bytes=handle.readBytes(Math.min(state.chunk_size||8*1024*1024,size-offset));
   try{state={...state,...await call(`${endpoint}/${id}?offset=${offset}`,'PUT',bytes.buffer)};failures=0;onProgress?.(state.offset/size)}
   catch(e){
    if(e instanceof TransferError&&e.status<500&&e.status!==409&&e.status!==429)throw e;
    if(++failures>2)throw e;
    await new Promise(resolve=>setTimeout(resolve,failures*1000));
    state=await call(`${endpoint}/${id}`);
   }
  }
 }finally{handle.close()}
 const result=await call(`${endpoint}/${id}/complete`,'POST');onProgress?.(1);return result;
}
