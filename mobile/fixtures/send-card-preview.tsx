// Local emulator-only fixture. Never calls the server or sends a message.
import { useState } from 'react';
import { FlatList, Text, TextInput, View, Pressable } from 'react-native';
import { SendCard } from '../send-card';
import { setUiLanguage } from '../ui-language';
void setUiLanguage('ja');
const original = 'しゅんさんへ\n\nスマホのアプリで操作できます。\nhttps://example.test/mobile\nよろしくお願いします。😀';
let saved = original;
let status = 'pending';
let fail = false;
const request = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  if (init && fail) throw new Error('Fixture network failure');
  if (init?.method === 'PATCH') saved = JSON.parse(String(init.body)).body;
  if (init?.method === 'POST') status = url.endsWith('/discard') ? 'rejected' : 'sent';
  return { id: 'fixture', status, content: saved, action_data: { channel: 'instagram_dm', to_name: 'テスト相手（送信されません）' } } as T;
};
export default function SendCardPreview() {
  const [key, setKey] = useState(0);
  const [paste, setPaste] = useState('');
  const [offline, setOffline] = useState(false);
  return <FlatList inverted data={['fixture']} keyExtractor={item=>item} style={{flex:1, backgroundColor:'#edf2ee'}} keyboardShouldPersistTaps="handled" renderItem={()=> <View style={{padding:18,paddingTop:48,gap:16}}>
    <Text style={{fontSize:20}}>送信案・編集とコピー確認</Text>
    <SendCard key={key} id="fixture" request={request}/>
    <Text>コピーした本文を、下の欄を長押しして貼り付け</Text>
    <TextInput accessibilityLabel="コピー確認の貼り付け欄" placeholder="ここに貼り付け" multiline value={paste} onChangeText={setPaste}
      style={{minHeight:120,borderWidth:1,borderColor:'#888',padding:12,backgroundColor:'white',textAlignVertical:'top'}}/>
    <Text selectable>{paste ? `貼り付け文字数: ${paste.length}` : '未貼り付け'}</Text>
    <View style={{flexDirection:'row',gap:14,flexWrap:'wrap'}}>
      <Pressable onPress={()=>{status='pending';saved=original;setKey(k=>k+1);setPaste('');}}><Text>カードを初期化</Text></Pressable>
      <Pressable onPress={()=>{fail=!fail;setOffline(fail);}}><Text>{offline?'通信失敗を解除':'送信・破棄を失敗させる'}</Text></Pressable>
    </View>
  </View>}/>;
}
