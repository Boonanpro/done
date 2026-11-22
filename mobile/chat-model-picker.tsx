import React, { useEffect, useState } from 'react';
import { Ionicons } from '@expo/vector-icons';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ui } from './ui-language';

type ModelOption = { id: string; label: string };
export type RoomModel = {
  effective_model: string;
  selected_model: string | null;
  fallback_reason?: 'usage_limit' | null;
  can_switch: boolean;
  options: ModelOption[];
};

type Props = {
  roomId: string;
  disabled: boolean;
  request: (path: string, init?: RequestInit) => Promise<RoomModel>;
};

export function ChatModelPicker({ roomId, disabled, request }: Props) {
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState<RoomModel>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const endpoint = `/chat/dan/sessions/${encodeURIComponent(roomId)}/model`;

  useEffect(() => {
    let active = true;
    if (open) setLoading(true);
    request(endpoint).then(
      (value) => { if (active) setModel(value); },
      () => { if (active && open) setError(ui('Could not load models.', 'モデルを読み込めませんでした。')); },
    ).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [endpoint, open, request]);

  const choose = async (id: string) => {
    if (disabled || loading || saving || !model?.can_switch) return;
    setSaving(true);
    setError('');
    try {
      const saved = await request(endpoint, { method: 'PATCH', body: JSON.stringify({ model: id }) });
      setModel(saved);
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : ui('Could not switch models.', 'モデルを切り替えられませんでした。'));
    } finally {
      setSaving(false);
    }
  };

  const label = (id: string) => model?.options.find((option) => option.id === id)?.label ?? id;
  const current = model ? label(model.effective_model) : ui('Model', 'モデル');

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={ui(`Chat model, ${current}`, `チャットのモデル、${current}`)}
        hitSlop={5}
        onPress={() => { setError(''); setOpen(true); }}
        style={styles.trigger}
      >
        <Text numberOfLines={1} style={styles.current}>{current}</Text>
        <Ionicons name="chevron-down" size={12} color="#1d6b57" />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => { if (!saving) setOpen(false); }}>
        <View style={styles.overlay}>
          <View style={styles.sheet} accessibilityViewIsModal>
            <View style={styles.heading}>
              <Text style={styles.title}>{ui('Chat model', 'チャットのモデル')}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel={ui('Close', '閉じる')} disabled={saving} onPress={() => setOpen(false)} hitSlop={10}>
                <Ionicons name="close" size={24} color="#162e27" />
              </Pressable>
            </View>
            {loading && <Text style={styles.note}>{ui('Loading…', '読み込み中…')}</Text>}
            {disabled && <Text style={styles.note}>{ui('Switch models after Dan finishes this turn.', 'ダンの返答が終わると切り替えられます。')}</Text>}
            {model?.fallback_reason === 'usage_limit' && model.selected_model && (
              <Text style={styles.note}>{ui(
                `Using ${current} while ${label(model.selected_model)} is at its usage limit.`,
                `${label(model.selected_model)} が利用上限のため、${current} で返答します。`,
              )}</Text>
            )}
            {model && !model.can_switch && <Text style={styles.note}>{ui('This chat cannot save a model.', 'この部屋ではモデルを変更できません。')}</Text>}
            {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
            <ScrollView>
              {model?.options.map((option) => {
                const selected = option.id === (model.selected_model ?? model.effective_model);
                const unavailable = disabled || loading || saving || !model.can_switch;
                return (
                  <Pressable
                    key={option.id}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: selected, disabled: unavailable }}
                    disabled={unavailable}
                    onPress={() => { void choose(option.id); }}
                    style={styles.option}
                  >
                    <Text style={styles.optionText}>{option.label}</Text>
                    {selected && <Ionicons name="checkmark" size={20} color="#1d6b57" />}
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: { alignItems: 'center', flexDirection: 'row', gap: 3, maxWidth: '100%' },
  current: { color: '#1d6b57', flexShrink: 1, fontSize: 11, fontWeight: '600' },
  overlay: { backgroundColor: '#10281e66', flex: 1, justifyContent: 'center', padding: 24 },
  sheet: { alignSelf: 'center', backgroundColor: '#fff', borderRadius: 16, maxHeight: '75%', maxWidth: 420, padding: 16, width: '100%' },
  heading: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  title: { color: '#162e27', fontSize: 18, fontWeight: '700' },
  note: { color: '#59685f', marginVertical: 6 },
  error: { color: '#a22525', marginVertical: 6 },
  option: { alignItems: 'center', borderBottomColor: '#edf2ef', borderBottomWidth: StyleSheet.hairlineWidth, flexDirection: 'row', justifyContent: 'space-between', minHeight: 48 },
  optionText: { color: '#162e27', flexShrink: 1, fontSize: 15 },
});
