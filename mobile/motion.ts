// チャットの動きの共通語彙（APK）。Web版と同じ物理: 200ms・減速・少し拡大しながら出る。
// reanimated 未導入のため LayoutAnimation（次のレイアウト変化を一括でアニメーション）。
// 「吹き出しが生まれる瞬間」だけに使い、文字が増える更新には掛けない。
import { LayoutAnimation, Platform, UIManager } from 'react-native';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

/** 次の描画更新（メッセージ追加・カード消滅など）をフェード＋位置の減速アニメで行う */
export function animateNextLayout(durationMs = 200): void {
  try {
    LayoutAnimation.configureNext({
      duration: durationMs,
      create: { type: LayoutAnimation.Types.easeOut, property: LayoutAnimation.Properties.scaleXY },
      update: { type: LayoutAnimation.Types.easeOut },
      delete: { type: LayoutAnimation.Types.easeOut, property: LayoutAnimation.Properties.opacity },
    });
  } catch {
    // アニメーション非対応環境では即時表示
  }
}

/** 送信ボタンなどの押下感（押した瞬間に少し縮む） */
export const pressedScale = ({ pressed }: { pressed: boolean }) => ({
  transform: [{ scale: pressed ? 0.9 : 1 }],
});
