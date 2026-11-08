import { useEffect, useRef, useState } from 'react';
import { Pressable, Text } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { ui } from './ui-language';

/** Copy the visible draft verbatim, without saving or sending the proposal. */
export function CopyBodyButton({ body, disabled = false, color = '#59685f', borderColor = '#cfdcd5' }: {
  body: string; disabled?: boolean; color?: string; borderColor?: string;
}) {
  const [state, setState] = useState<'idle' | 'copying' | 'copied' | 'error'>('idle');
  const inFlight = useRef(false);
  const currentBody = useRef(body);
  currentBody.current = body;
  useEffect(() => { setState('idle'); }, [body]);

  const copy = async () => {
    if (disabled || !body || inFlight.current) return;
    inFlight.current = true;
    setState('copying');
    try {
      const copied = await Clipboard.setStringAsync(body);
      if (currentBody.current === body) setState(copied ? 'copied' : 'error');
    } catch {
      if (currentBody.current === body) setState('error');
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <Pressable accessibilityRole="button" accessibilityLabel={ui('Copy message body', '本文をコピー')}
      disabled={disabled || !body || state === 'copying'} onPress={copy}
      style={({ pressed }) => ({ borderWidth: 1, borderColor, borderRadius: 999,
        paddingHorizontal: 14, paddingVertical: 8, justifyContent: 'center',
        opacity: pressed || disabled || !body ? 0.5 : 1 })}>
      <Text accessibilityLiveRegion="polite" style={{ color: state === 'error' ? '#a2413b' : color, fontSize: 13 }}>
        {state === 'copied' ? ui('Copied', 'コピーしました') : state === 'error' ? ui('Retry copy', 'コピー失敗・再試行')
          : state === 'copying' ? ui('Copying…', 'コピー中…') : ui('Copy', 'コピー')}
      </Text>
    </Pressable>
  );
}
