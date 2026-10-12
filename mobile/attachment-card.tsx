import React,{useEffect,useState} from 'react';
import {Image,Pressable,StyleSheet,Text,View} from 'react-native';
import {Ionicons} from '@expo/vector-icons';
import * as Thumbnails from 'expo-video-thumbnails';
import {ui} from './ui-language';
export function AttachmentCard({uri,name,mime,size,onRemove}:{uri:string;name:string;mime:string;size?:number;onRemove:()=>void}){
 const video=mime.startsWith('video/'),photo=mime.startsWith('image/'),audio=mime.startsWith('audio/')||/\.(mp3|wav|m4a|aac|ogg|flac|opus)$/i.test(name);
 const [thumbnail,setThumbnail]=useState<string>();
 useEffect(()=>{let live=true;if(video)void Thumbnails.getThumbnailAsync(uri,{time:0}).then(x=>{if(live)setThumbnail(x.uri)}).catch(()=>{});return()=>{live=false}},[uri,video]);
 return <View style={s.card}>
  <View style={[s.art,audio&&{backgroundColor:'#e2eae7'}]}>
   {(photo||thumbnail)?<Image source={{uri:photo?uri:thumbnail}} style={StyleSheet.absoluteFill} resizeMode="cover"/>:<Ionicons name={audio?'musical-notes-outline':video?'videocam-outline':'document-text-outline'} size={30} color="#315c4c"/>}
   {audio&&<View style={s.wave}>{[8,16,25,12,32,21,10,26,18,8].map((h,i)=><View key={i} style={{height:h,width:3,borderRadius:2,backgroundColor:'#769d8d'}}/>)}</View>}
   {video&&<View style={s.play}><Ionicons name="play" size={18} color="white"/></View>}
  </View>
  <View style={s.caption}><Text numberOfLines={1} style={s.name}>{name}</Text><Text style={s.meta}>{audio?ui('Audio','音声'):video?ui('Video','動画'):photo?ui('Photo','画像'):ui('File','ファイル')}{size?` · ${size<1024*1024?`${Math.max(1,Math.round(size/1024))} KB`:`${(size/1024/1024).toFixed(1)} MB`}`:''}</Text></View>
  <Pressable accessibilityRole="button" accessibilityLabel={ui(`Remove ${name}`,`${name}を外す`)} onPress={onRemove} style={s.remove}><Ionicons name="close" size={17} color="white"/></Pressable>
 </View>;
}
const s=StyleSheet.create({card:{width:126,borderRadius:16,overflow:'hidden',backgroundColor:'#f1f4f2',borderWidth:1,borderColor:'#dce5df'},art:{height:88,backgroundColor:'#e1e8e3',alignItems:'center',justifyContent:'center'},wave:{flexDirection:'row',gap:4,alignItems:'center',height:34,marginTop:2},play:{position:'absolute',bottom:8,left:8,width:28,height:28,borderRadius:14,backgroundColor:'#0008',alignItems:'center',justifyContent:'center'},caption:{paddingHorizontal:9,paddingVertical:8,gap:3},name:{fontSize:12,fontWeight:'600',color:'#263b31'},meta:{fontSize:10,color:'#65776d'},remove:{position:'absolute',right:0,top:0,width:40,height:40,alignItems:'center',justifyContent:'center',backgroundColor:'#0008',borderBottomLeftRadius:16}});
