import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, BackHandler, FlatList, KeyboardAvoidingView, Pressable, RefreshControl, StyleSheet, Text, TextInput, View} from 'react-native';
import {Ionicons} from '@expo/vector-icons';
import {ui, useUiLanguage} from './ui-language';
import {doneColors as C} from './done-dashboard';
import type {CollabRoomSummary} from './collab';

type Request = <T = any>(path:string, options?:any)=>Promise<T>;
export function CollabRoomsScreen({request,onOpenRoom,topInset}:{request:Request;onOpenRoom:(r:CollabRoomSummary)=>void;topInset:number}) {
 useUiLanguage();
 const [rooms,setRooms]=useState<CollabRoomSummary[]>([]),[loading,setLoading]=useState(true),[loadError,setLoadError]=useState(false);
 const [mode,setMode]=useState<'list'|'profile'|'create'>('list');
 const [name,setName]=useState(''),[nameDraft,setNameDraft]=useState(''),[title,setTitle]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const pending=useRef(false),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
 const load=useCallback(async()=>{try{const d=await request<{rooms:CollabRoomSummary[]}>('/collab/rooms');if(alive.current){setRooms(d.rooms);setLoadError(false)}}catch{if(alive.current)setLoadError(true)}finally{if(alive.current)setLoading(false)}},[request]);
 useEffect(()=>{void load();const timer=setInterval(()=>void load(),20000);return()=>clearInterval(timer)},[load]);
 useEffect(()=>{request<{display_name?:string;email?:string}>('/chat/me').then(u=>{if(alive.current)setName(u.display_name||(u.email||'').split('@')[0]||'')}).catch(()=>{});},[request]);
 useEffect(()=>{const sub=BackHandler.addEventListener('hardwareBackPress',()=>{if(mode!=='list'){if(!pending.current){setMode('list');setError('')}return true}return false});return()=>sub.remove()},[mode]);
 const open=(next:'profile'|'create')=>{setError('');if(next==='profile')setNameDraft(name);setMode(next)};
 const save=async()=>{
  const value=(mode==='profile'?nameDraft:title).trim();if(!value||pending.current)return;
  pending.current=true;setBusy(true);setError('');
  try{
   if(mode==='profile'){await request('/chat/profile',{method:'POST',body:JSON.stringify({display_name:value})});if(alive.current){setName(value);setMode('list')}}
   else{const room=await request<CollabRoomSummary>('/collab/rooms',{method:'POST',body:JSON.stringify({title:value})});if(alive.current){setTitle('');setMode('list');setRooms(prev=>[room,...prev]);onOpenRoom(room)}}
  }catch{if(alive.current)setError(mode==='profile'?ui('Could not save. Please try again.','保存できませんでした。もう一度お試しください。'):ui('Could not confirm creation. Check the list before trying again.','作成を確認できませんでした。一覧を確認してから再試行してください。'))}
  finally{pending.current=false;if(alive.current)setBusy(false)}
 };
 const icon=(glyph:React.ComponentProps<typeof Ionicons>['name'],label:string,press:()=>void,avatar=false)=><Pressable accessibilityRole="button" accessibilityLabel={label} disabled={busy} onPress={press} style={s.icon}><View style={avatar?s.avatar:undefined}><Ionicons accessible={false} name={glyph} size={23} color={C.ink}/></View></Pressable>;
 return <KeyboardAvoidingView style={[s.root,{paddingTop:topInset}]} behavior="height">
  <View style={s.header}>{mode!=='list'&&icon('arrow-back',ui('Back','戻る'),()=>{setMode('list');setError('')})}<Text style={[s.title,mode!=='list'&&{fontSize:21}]}>{mode==='list'?ui('Collab','コラボ'):mode==='profile'?ui('Your profile','プロフィール'):ui('New collab chat','新しいコラボチャット')}</Text>{mode==='list'&&<>{icon('add',ui('New collab chat','新しいコラボチャット'),()=>open('create'))}{icon('person-outline',ui('Your profile','プロフィール'),()=>open('profile'),true)}</>}</View>
  {mode!=='list'?<View style={s.form}>
   {mode==='profile'&&<View style={s.largeAvatar}><Ionicons name="person-outline" size={38} color={C.accent}/></View>}
   <Text style={s.label}>{mode==='profile'?ui('Display name','表示名'):ui('Chat name','チャット名')}</Text>
   <TextInput accessibilityLabel={mode==='profile'?ui('Display name','表示名'):ui('Chat name','チャット名')} value={mode==='profile'?nameDraft:title} onChangeText={mode==='profile'?setNameDraft:setTitle} maxLength={mode==='profile'?100:200} editable={!busy} style={s.input} placeholderTextColor={C.muted} returnKeyType="done" onSubmitEditing={()=>void save()}/>
   {!!error&&<Text accessibilityRole="alert" style={s.error}>{error}</Text>}
   <Pressable accessibilityRole="button" disabled={busy||!(mode==='profile'?nameDraft:title).trim()} onPress={()=>void save()} style={[s.save,(busy||!(mode==='profile'?nameDraft:title).trim())&&{opacity:.45}]}>{busy?<ActivityIndicator color="#fff"/>:<Text style={s.saveText}>{mode==='profile'?ui('Save','保存'):ui('Create chat','チャットを作成')}</Text>}</Pressable>
  </View>:<>
   {loadError&&<Pressable accessibilityRole="button" onPress={()=>{setLoading(true);void load()}} style={s.notice}><Text style={s.error}>{ui('Could not load rooms. Tap to retry.','読み込めませんでした。タップして再試行。')}</Text></Pressable>}
   {loading&&rooms.length===0?<ActivityIndicator style={{marginTop:40}} color={C.accent}/>:<FlatList contentContainerStyle={s.list} data={rooms} keyExtractor={r=>r.id} refreshControl={<RefreshControl refreshing={loading} onRefresh={()=>{setLoading(true);void load()}} tintColor={C.accent}/>} ListEmptyComponent={!loadError?<View style={s.empty}><Ionicons name="people-outline" size={36} color={C.muted}/><Text style={s.label}>{ui('No shared rooms yet','共同ルームはまだありません')}</Text><Pressable accessibilityRole="button" style={s.save} onPress={()=>open('create')}><Text style={s.saveText}>{ui('Create chat','チャットを作成')}</Text></Pressable></View>:null} renderItem={({item})=><Pressable accessibilityRole="button" accessibilityLabel={item.title} onPress={()=>onOpenRoom(item)} style={s.row}><View style={s.roomAvatar}><Ionicons accessible={false} name="people-outline" size={23} color={C.accent}/></View><View style={{flex:1,minWidth:0}}><Text numberOfLines={1} style={s.roomTitle}>{item.title}</Text><Text numberOfLines={1} style={s.preview}>{item.last_message||ui('No messages yet','メッセージはまだありません')}</Text></View><View style={s.meta}><Text style={s.time}>{formatTime(item.last_message_at||item.updated_at)}</Text>{!!(item.unread_count||item.unread)&&<Text style={s.badge}>{item.unread_count?item.unread_count>99?'99+':item.unread_count:'•'}</Text>}</View></Pressable>}/>}</>}
 </KeyboardAvoidingView>;
}
function formatTime(value:string){const d=new Date(value);if(!value||Number.isNaN(d.getTime()))return '';return d.toDateString()===new Date().toDateString()?d.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):`${d.getMonth()+1}/${d.getDate()}`}
const s=StyleSheet.create({root:{flex:1,backgroundColor:C.background},header:{height:72,paddingHorizontal:20,flexDirection:'row',alignItems:'center'},title:{flex:1,fontSize:28,fontWeight:'600',color:C.ink},icon:{width:48,height:48,alignItems:'center',justifyContent:'center'},avatar:{width:34,height:34,borderRadius:17,backgroundColor:C.tint,alignItems:'center',justifyContent:'center'},list:{paddingHorizontal:22},row:{minHeight:76,paddingVertical:12,borderBottomWidth:1,borderColor:C.line,flexDirection:'row',alignItems:'center',gap:12},roomAvatar:{width:40,height:40,borderRadius:20,backgroundColor:C.tint,alignItems:'center',justifyContent:'center'},roomTitle:{fontSize:15,fontWeight:'600',color:C.ink,marginBottom:5},preview:{fontSize:12,color:C.muted},meta:{alignItems:'flex-end',gap:8,alignSelf:'flex-start'},time:{fontSize:10,color:C.muted},badge:{backgroundColor:C.accent,color:'#fff',borderRadius:12,minWidth:21,textAlign:'center',padding:4,fontSize:11},form:{paddingHorizontal:22},largeAvatar:{width:76,height:76,borderRadius:38,backgroundColor:C.tint,alignSelf:'center',alignItems:'center',justifyContent:'center',marginVertical:20},label:{color:C.ink,fontSize:13,marginVertical:12},input:{height:50,borderWidth:1,borderColor:C.line,borderRadius:12,backgroundColor:'#fff',color:C.ink,paddingHorizontal:12,fontSize:16},save:{minHeight:50,backgroundColor:C.accent,borderRadius:12,alignItems:'center',justifyContent:'center',paddingHorizontal:20,marginTop:20},saveText:{color:'#fff',fontSize:15,fontWeight:'600'},error:{color:'#973e30',fontSize:13,lineHeight:20,marginVertical:12},notice:{paddingHorizontal:22},empty:{alignItems:'center',paddingVertical:45}});
