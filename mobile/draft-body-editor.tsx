import { useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View, type StyleProp, type TextStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CopyBodyButton } from './copy-body-button';
import { ui } from './ui-language';

/** Android selection handles cannot track coordinates inside an inverted list.
 * The native modal gives editing its own untransformed window and keyboard space. */
export function DraftBodyEditor({ value, onChangeText, editable = true, onFocus, onBlur, style }: {
  value: string; onChangeText: (text: string) => void; editable?: boolean;
  onFocus?: () => void; onBlur?: () => void; style?: StyleProp<TextStyle>;
}) {
  const [open, setOpen] = useState(false);
  const finish = () => { setOpen(false); onBlur?.(); };
  return <>
    <Pressable accessibilityRole="button" accessibilityLabel={ui('Edit message body', '本文を編集')}
      disabled={!editable} onPress={() => { onFocus?.(); setOpen(true); }}>
      <Text style={style} numberOfLines={8}>{value || ui('Write a message', '本文を入力')}</Text>
      <Text style={styles.hint}>{ui('Edit body', '本文を編集')}</Text>
    </Pressable>
    <Modal visible={open} animationType="slide" onRequestClose={finish}>
      <SafeAreaView style={styles.screen}>
        <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.header}>
            <Text style={styles.title}>{ui('Edit message', '本文を編集')}</Text>
            <Pressable accessibilityRole="button" onPress={finish} style={styles.finish}>
              <Text style={styles.finishText}>{ui('Done editing', '編集を終える')}</Text>
            </Pressable>
          </View>
          <TextInput accessibilityLabel={ui('Message body', '送信案の本文')} style={styles.input}
            value={value} onChangeText={onChangeText} editable={editable} multiline autoFocus
            textAlignVertical="top" scrollEnabled />
          <View style={styles.footer}>
            <CopyBodyButton body={value} disabled={!editable} />
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  </>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#ffffff' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: 16 },
  title: { fontSize: 17, fontWeight: '700', color: '#162e27' },
  finish: { padding: 10, borderRadius: 20, backgroundColor: '#245e49' },
  finishText: { fontSize: 14, color: '#fff' },
  input: { flex: 1, marginHorizontal: 16, padding: 12, fontSize: 17, lineHeight: 26, color: '#162e27', borderWidth: 1, borderColor: '#cfdcd5', borderRadius: 12 },
  footer: { alignItems: 'flex-end', padding: 16 },
  hint: { color: '#59685f', fontSize: 12, marginTop: 6 },
});
