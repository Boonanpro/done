import React, {createContext, useContext, useRef, useState} from 'react';
import {ActivityIndicator, Alert, FlatList, Image, Linking, Modal, Platform, Pressable, StyleSheet, Text, ToastAndroid, View, useWindowDimensions} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {useVideoPlayer, VideoView, type VideoPlayer} from 'expo-video';
import {useEvent} from 'expo';
import {Directory, File, Paths} from 'expo-file-system';
import * as MediaLibrary from 'expo-media-library';
import {Ionicons} from '@expo/vector-icons';
import {ui} from './ui-language';
import {useMediaRotation} from './media-rotation';
import {useMediaImmersive} from './media-immersive';
import {ZoomImage} from './zoom-image';

export type GalleryItem={url:string;kind:'image'|'video';name?:string};
export function mediaKind(url:string):GalleryItem['kind']|null {
 const path=url.split(/[?#]/)[0];
 if(/\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(path))return 'video';
 if(/\.(png|jpe?g|gif|webp|avif|heic|bmp)$/i.test(path))return 'image';
 return null;
}
export function uniqueMedia(items:GalleryItem[]){return items.filter((x,i)=>items.findIndex(y=>y.url===x.url)===i)}
export function fileMediaKind(file:{type?:string;url:string;name?:string}):GalleryItem['kind']|null{return file.type?.startsWith('image/')?'image':file.type?.startsWith('video/')?'video':mediaKind(file.url)||mediaKind(file.name||'')}
const GalleryContext=createContext<((item:GalleryItem)=>void)|null>(null);
export const useMediaGallery=()=>useContext(GalleryContext);
export function MediaGalleryScope({items,children}:{items:GalleryItem[];children:React.ReactNode}){
 const [selection,setSelection]=useState<{items:GalleryItem[];url:string}|null>(null);
 return <GalleryContext.Provider value={item=>setSelection({items:uniqueMedia([...items,item]),url:item.url})}>{children}{selection&&<MediaViewer items={selection.items} initialUrl={selection.url} onClose={()=>setSelection(null)}/>}</GalleryContext.Provider>;
}
// 端末の写真（ギャラリー）へ保存する。URL を一時ファイルへ落としてから MediaStore に登録し、一時ファイルは消す。
// Android 13 以上は書き込みに許可が要らない。12 以下だけ「写真へのアクセス」を求める。
function saveFileName(item:GalleryItem){
 const fromUrl=decodeURIComponent(item.url.split(/[?#]/)[0].split('/').pop()||'');
 const base=(item.name&&/\.[a-z0-9]{2,5}$/i.test(item.name)?item.name:fromUrl).replace(/[\\/:*?"<>|]/g,'_');
 if(/\.[a-z0-9]{2,5}$/i.test(base))return base;
 return `${base||'done-media'}.${item.kind==='video'?'mp4':'jpg'}`;
}
export async function saveMediaToPhotos(item:GalleryItem):Promise<'saved'|'denied'>{
 if(Platform.OS==='android'&&typeof Platform.Version==='number'&&Platform.Version<33){
  const permission=await MediaLibrary.requestPermissionsAsync(true);
  if(!permission.granted)return 'denied';
 }
 const dir=new Directory(Paths.cache,'media-save');
 dir.create({idempotent:true,intermediates:true});
 const target=new File(dir,saveFileName(item));
 if(target.exists)target.delete();
 const file=await File.downloadFileAsync(item.url,target);
 try{await MediaLibrary.saveToLibraryAsync(file.uri)}finally{try{file.delete()}catch{}}
 return 'saved';
}
function SaveButton({item,style}:{item:GalleryItem;style:object}){
 const [state,setState]=useState<'idle'|'saving'|'saved'>('idle');
 const current=useRef(item.url);current.current=item.url;
 const save=async()=>{
  if(state==='saving')return;
  setState('saving');
  try{
   const result=await saveMediaToPhotos(item);
   if(current.current!==item.url)return;
   if(result==='denied'){setState('idle');Alert.alert(ui('Permission required','権限が必要です'),ui('Allow photo access in your device settings to save media.','保存するには、設定アプリから写真へのアクセスを許可してください。'));return}
   setState('saved');
   if(Platform.OS==='android')ToastAndroid.show(ui(item.kind==='video'?'Video saved to Photos':'Image saved to Photos',item.kind==='video'?'動画を写真に保存しました':'画像を写真に保存しました'),ToastAndroid.SHORT);
  }catch(error){
   if(current.current!==item.url)return;
   setState('idle');
   Alert.alert(ui('Could not save','保存できませんでした'),String((error as Error)?.message||error));
  }
 };
 return <Pressable accessibilityRole="button" accessibilityState={{busy:state==='saving'}} accessibilityLabel={ui(item.kind==='video'?'Save video to Photos':'Save image to Photos',item.kind==='video'?'動画を写真に保存':'画像を写真に保存')} onPress={()=>void save()} style={[s.button,s.close,style]}>{state==='saving'?<ActivityIndicator color="#fff"/>:<Ionicons name={state==='saved'?'checkmark':'download-outline'} size={26} color="#fff"/>}</Pressable>;
}
export function MediaViewer({items,initialUrl,onClose}:{items:GalleryItem[];initialUrl:string;onClose:()=>void}){
 useMediaRotation();
 const immersiveReady=useMediaImmersive();
 const {width,height}=useWindowDimensions(),insets=useSafeAreaInsets();
 const [frame,setFrame]=useState({width,height:height});
 const [index,setIndex]=useState(()=>Math.max(0,items.findIndex(x=>x.url===initialUrl)));
 // 写真を拡大している間は横送りを止める（指で動かすと拡大した写真の中を見る）
 const [zoomed,setZoomed]=useState(false);
 // The player belongs to the gallery, not a virtualized page: resizing a long
 // list can temporarily recycle the selected page without interrupting playback.
 const videoSource=items[index]?.kind==='video'?items[index].url:null;
 const player=useVideoPlayer(videoSource,p=>{p.loop=false;if(videoSource)p.play()});
 const selectedIndex=useRef(index);selectedIndex.current=index;
 const list=useRef<FlatList<GalleryItem>>(null);
 // Recreate only the paging surface when its width changes. The player above
 // stays mounted and retains playback while native clipping bounds reset.
 return <Modal visible={immersiveReady} hardwareAccelerated animationType="fade" onRequestClose={onClose} statusBarTranslucent navigationBarTranslucent supportedOrientations={['portrait','portrait-upside-down','landscape-left','landscape-right']}>
  <View style={s.root}>
   <View style={{flex:1,minHeight:0}} onLayout={e=>{const {width,height}=e.nativeEvent.layout;if(width>0&&height>0)setFrame(previous=>previous.width===width&&previous.height===height?previous:{width,height})}}>
    <FlatList key={frame.width} ref={list} data={items} horizontal pagingEnabled scrollEnabled={!zoomed} removeClippedSubviews={false} initialScrollIndex={index} getItemLayout={(_,i)=>({length:frame.width,offset:frame.width*i,index:i})} keyExtractor={(x,i)=>`${x.url}-${i}`} showsHorizontalScrollIndicator={false} extraData={index} windowSize={3} initialNumToRender={1} maxToRenderPerBatch={3} onContentSizeChange={()=>list.current?.scrollToOffset({offset:selectedIndex.current*frame.width,animated:false})} onMomentumScrollEnd={e=>setIndex(Math.max(0,Math.min(items.length-1,Math.round(e.nativeEvent.contentOffset.x/e.nativeEvent.layoutMeasurement.width))))} renderItem={({item,index:i})=><View style={{width:frame.width,height:frame.height}}>{i===index?<MediaPage key={item.url} item={item} player={player} onZoomChange={setZoomed}/>:<View style={s.root}/>}</View>}/>
   </View>
   <Pressable accessibilityRole="button" accessibilityLabel={ui('Close media','メディアを閉じる')} onPress={onClose} style={[s.button,s.close,{top:Math.max(insets.top,12),right:Math.max(insets.right,12)}]}><Ionicons name="close" size={26} color="#fff"/></Pressable>
   {items[index]&&<SaveButton key={items[index].url} item={items[index]} style={{top:Math.max(insets.top,12),right:Math.max(insets.right,12)+60}}/>}
  </View>
 </Modal>;
}
function MediaPage({item,player,onZoomChange}:{item:GalleryItem;player:VideoPlayer;onZoomChange:(zoomed:boolean)=>void}){
 const [attempt,setAttempt]=useState(0),[error,setError]=useState(false),[loading,setLoading]=useState(true);
 if(item.kind==='video')return <ViewerVideo url={item.url} player={player} onRetry={()=>void player.replaceAsync(item.url).then(()=>player.play()).catch(()=>{})}/>;
 return <View style={s.root}><ZoomImage key={attempt} source={{uri:item.url}} onZoomChange={onZoomChange} accessibilityLabel={item.name||ui('Photo','画像')} onLoadStart={()=>setLoading(true)} onLoadEnd={()=>setLoading(false)} onError={()=>setError(true)}/>{loading&&!error&&<ActivityIndicator style={s.center} color="#fff"/>}{error&&<Failure retry={()=>{setError(false);setAttempt(x=>x+1)}}/>}</View>;
}
function ViewerVideo({url,player,onRetry}:{url:string;player:VideoPlayer;onRetry:()=>void}){
 const {status}=useEvent(player,'statusChange',{status:player.status});
 return <View style={s.root}><VideoView player={player} style={StyleSheet.absoluteFill} contentFit="contain" surfaceType="textureView" nativeControls fullscreenOptions={{enable:false}}/>{status==='loading'&&<ActivityIndicator pointerEvents="none" style={s.center} color="#fff"/>}{status==='error'&&<View style={s.center}><Text style={s.text}>{ui('This video cannot play here. The original file is available.','この動画はここでは再生できません。元のファイルは保存されています。')}</Text><Pressable accessibilityRole="button" accessibilityLabel={ui('Open original file','元のファイルを開く')} onPress={()=>void Linking.openURL(url).catch(()=>{})} style={s.button}><Ionicons name="download-outline" size={28} color="#fff"/><Text style={s.text}>{ui('Open file','ファイルを開く')}</Text></Pressable><Pressable accessibilityRole="button" accessibilityLabel={ui('Retry','再試行')} onPress={onRetry} style={s.button}><Ionicons name="refresh" size={26} color="#fff"/></Pressable></View>}</View>;
}
function Failure({retry}:{retry:()=>void}){return <View style={s.center}><Text style={s.text}>{ui('Could not load this media','メディアを読み込めませんでした')}</Text><Pressable accessibilityRole="button" onPress={retry} style={s.button}><Ionicons name="refresh" size={26} color="#fff"/><Text style={s.text}>{ui('Retry','再試行')}</Text></Pressable></View>}
const s=StyleSheet.create({root:{flex:1,backgroundColor:'#000'},close:{position:'absolute',borderRadius:24,backgroundColor:'rgba(0,0,0,.35)'},button:{minWidth:48,minHeight:48,alignItems:'center',justifyContent:'center'},text:{color:'#fff',fontSize:14},center:{...StyleSheet.absoluteFillObject,alignItems:'center',justifyContent:'center',gap:16}});
