吉川特装自動車様向けの営業提案動画ですね。参考動画「Claude for Word」のスタイリッシュな演出（ズームイン/アウト、カーソルのオンオフ、テキスト挿入）を踏襲し、経営者に直感的に価値が伝わる構成で作成しました。

以下に「1. シーン設計書」「2. Playwright録画スクリプト」「3. Remotionコード」を出力します。

---

### 1. シーン設計書

#### シーン 1: [検索からアクセス]
**秒数**: 0-5秒（150フレーム）
**物語上の役割**: フック / アクセス手順
**視聴者に感じさせたいこと**: 「自社を探しているお客様はこういう行動をとるのか」という共感とリアリティ
**そのために何を映すか**: Google検索窓に「鳥取 特装車 修理」と打ち込まれ、自社のHPがヒットする様子
**操作の流れ**: 検索窓に文字がタイピングされる。その後カーソルが現れ、検索結果のリンクへ移動。リンクをクリックし、HPのファーストビューが開く。開いた直後にカーソルは非表示。
**前のシーンからの繋がり**: 動画の開始。機能から入るのではなく、ユーザーの現実のタスク（検索）から入ることで物語性を生む。
**編集演出**: タイピング音を挿入。リンクにカーソルが近づく際にズームイン（1.4倍）。クリック音と共にHPへ遷移し、スムーズにズームアウトして全体を表示する。

#### シーン 2: [ファーストビューのインパクト]
**秒数**: 5-9秒（120フレーム）
**物語上の役割**: 自社ブランドの再確認
**視聴者に感じさせたいこと**: 「おっ、うちの会社が綺麗にまとまっている」という驚きと期待
**そのために何を映すか**: 整備中の写真と「新明和認定サービス工場」という信頼感のあるキャッチコピー
**操作の流れ**: カーソルは非表示（無駄な動きを排除）。画面はスクロールせず固定。
**前のシーンからの繋がり**: 検索から辿り着いたユーザーが最初に見る景色を提示。
**編集演出**: 画面中央のキャッチコピーに向けてゆっくりとズームイン（1.3倍）。その後、次のシーンに向けて全体表示へ戻る。

#### シーン 3: [テキスト挿入: 課題の可視化]
**秒数**: 9-11秒（60フレーム）
**物語上の役割**: テキスト挿入
**視聴者に感じさせたいこと**: 「確かにその通りだ」という納得感
**そのために何を映すか**: 無地の濃紺背景に白字で「特装車のトラブル、ネットで探すお客様に選ばれるために。」というメッセージ
**操作の流れ**: なし（背景がフェードインして画面を覆う）
**前のシーンからの繋がり**: ファーストビューを見せた後、なぜこのHPが必要なのかを端的な言葉で伝える。
**編集演出**: イーズイン・イーズアウトを伴うフェードイン・フェードアウト。落ち着いたテンポを作る。

#### シーン 4: [強みとサービスのスクロール]
**秒数**: 11-18秒（210フレーム）
**物語上の役割**: タスク遂行（サービス内容の確認）
**視聴者に感じさせたいこと**: 「自分たちの専門性がしっかり伝わる構成になっている」という安心感
**そのために何を映すか**: 選ばれる理由、サービス一覧、対応車種のセクションが次々とスクロールされる様子
**操作の流れ**: 下へ向かってスムーズにスクロールが進む。カーソルは非表示。
**前のシーンからの繋がり**: テキストのメッセージを裏付けるように、実際のコンテンツの充実度を見せる。
**編集演出**: スクロール中に「対応車種」の写真部分で1.3倍にズームイン。詳細を見せた後、スクロールが続く中で再びズームアウトする。

#### シーン 5: [テキスト挿入: 信頼の証明]
**秒数**: 18-20秒（60フレーム）
**物語上の役割**: テキスト挿入
**視聴者に感じさせたいこと**: 専門性の価値の再認識
**そのために何を映すか**: 無地背景に「専門技術と実績を、一目で伝わる形に。」
**操作の流れ**: なし
**前のシーンからの繋がり**: サービス一覧を見た後の総括。
**編集演出**: フェードイン・アウト。視聴者の情報処理のインターバル（小休止）として機能させる。

#### シーン 6: [問い合わせ導線]
**秒数**: 20-25秒（150フレーム）
**物語上の役割**: タスク遂行の完了（アクション）
**視聴者に感じさせたいこと**: 「ここから実際の仕事（電話）に繋がるんだな」という明確な因果関係
**そのために何を映すか**: フッターのお問い合わせセクション（電話番号）
**操作の流れ**: 画面が下部へスクロール。非表示だったカーソルが再び現れ、電話番号に向かって移動し、クリックする。
**前のシーンからの繋がり**: HPを見たユーザーが最後に行う「問い合わせ」というゴール地点を見せる。
**編集演出**: 電話番号に大きくズームイン（1.5倍）。クリック音を鳴らし、行動喚起の完了を聴覚的にも強調する。

#### シーン 7: [締め]
**秒数**: 25-28秒（90フレーム）
**物語上の役割**: 締め
**視聴者に感じさせたいこと**: プロフェッショナルな提案への信頼感
**そのために何を映すか**: 黒背景に「吉川特装自動車」「新しいWebサイトのご提案」のテキスト
**操作の流れ**: なし
**前のシーンからの繋がり**: デモを終え、提案動画としてのパッケージを閉じる。
**編集演出**: フェードイン。動画の最後まで表示をキープして終了。

---

### 2. Playwright録画スクリプト (Python)

HPのネットワーク遅延を排除し、滑らかなスクロールを記録するために、一定間隔でスクロールしながら1フレームずつPNGとして保存します。

```python
# record_video.py
from playwright.sync_api import sync_playwright
import os
import math

def record_video():
    os.makedirs('frames', exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        frame_count = 0
        
        def save_frame():
            nonlocal frame_count
            # Remotionで読み込みやすいように連番PNGで保存
            page.screenshot(path=f"frames/f_{frame_count:05d}.png")
            frame_count += 1

        # ==========================================
        # シーン1: 検索モックアップ (0-149 frames)
        # ==========================================
        html = """
        <html><body style="font-family: sans-serif; padding: 50px; background: #fff;">
            <div style="max-width: 800px; margin: 0 auto; padding-top: 50px;">
                <h1 style="color: #4285F4; font-size: 48px; margin-bottom: 20px;">Google</h1>
                <input id="search-box" type="text" value="" style="width: 100%; padding: 15px 25px; font-size: 20px; border-radius: 24px; border: 1px solid #dfe1e5; outline: none; box-shadow: 0 1px 6px rgba(32,33,36,.28);" readonly/>
                <div style="margin-top: 40px;">
                    <div style="color: #202124; font-size: 14px; margin-bottom: 5px;">yoshikawa-tokuso.vercel.app</div>
                    <a href="#" style="color: #1a0dab; font-size: 24px; text-decoration: none;">吉川特装自動車 | 鳥取県の新明和認定サービス工場</a>
                    <div style="color: #4d5156; margin-top: 8px; font-size: 16px;">ダンプカー、タンクローリー、パワーゲート等の特装車の修理・整備はお任せください。</div>
                </div>
            </div>
        </body></html>
        """
        page.set_content(html)
        
        # タイピングアニメーション (0-29 frames)
        text = "鳥取 特装車 修理"
        for i in range(1, len(text) + 1):
            page.evaluate(f'document.getElementById("search-box").value = "{text[:i]}"')
            save_frame()
            save_frame()
            save_frame() # 1文字につき3フレーム消費 (計27フレーム)
        for _ in range(3): save_frame() # 端数調整して30フレームに
        
        # クリックまでの待機・移動時間 (30-59 frames)
        for _ in range(30): save_frame()
        
        # クリック直後の待機 (60-74 frames)
        for _ in range(15): save_frame()
        
        # HPへ遷移 (遅延を動画に含めないための処理)
        page.goto('https://yoshikawa-tokuso.vercel.app')
        page.wait_for_load_state('networkidle')
        # 画像を遅延読み込みさせるため一度下までスクロールして戻る
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(2000)
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(1000)

        # ファーストビュー表示状態 (75-149 frames)
        for _ in range(75): save_frame()
        
        # ==========================================
        # シーン2: ファーストビューインパクト (150-269 frames)
        # ==========================================
        for _ in range(120): save_frame()
        
        # ==========================================
        # シーン3: テキスト挿入待機 (270-329 frames)
        # ==========================================
        for _ in range(60): save_frame()
        
        # ==========================================
        # シーン4: 強みとサービスのスクロール (330-539 frames)
        # ==========================================
        # スクロールアニメーション (約2200pxまでイーズインアウトで移動)
        for i in range(210):
            progress = i / 210
            ease_progress = progress * progress * (3 - 2 * progress)
            scroll_y = int(ease_progress * 2200)
            page.evaluate(f'window.scrollTo(0, {scroll_y})')
            save_frame()
            
        # ==========================================
        # シーン5: テキスト挿入待機 (540-599 frames)
        # ==========================================
        for _ in range(60): save_frame()
            
        # ==========================================
        # シーン6: 問い合わせ導線スクロール (600-749 frames)
        # ==========================================
        # お問い合わせ(フッター)までスクロール
        start_y = 2200
        # ページの一番下付近をターゲットに
        target_y = page.evaluate('document.body.scrollHeight') - 1080
        
        for i in range(150):
            progress = i / 150
            ease_progress = progress * progress * (3 - 2 * progress)
            scroll_y = int(start_y + ease_progress * (target_y - start_y))
            page.evaluate(f'window.scrollTo(0, {scroll_y})')
            save_frame()
            
        # ==========================================
        # シーン7: 締め待機 (750-839 frames)
        # ==========================================
        for _ in range(90): save_frame()
            
        browser.close()
        print(f"Total frames generated: {frame_count}") # 840になるはずです

if __name__ == "__main__":
    record_video()
```

---

### 3. Remotionコード (TypeScript)

`src`ディレクトリ内に以下の3つのファイルを作成します。また、Playwrightで生成した`frames`ディレクトリと音声ファイル（`click.mp3`, `typing.mp3`, `bgm.mp3`）を`public`ディレクトリ直下に配置してください。

#### ① src/index.tsx
```tsx
import { registerRoot } from "remotion";
import { Root } from "./Root";

// エントリポイントの登録
registerRoot(Root);
```

#### ② src/Root.tsx
```tsx
import { Composition } from "remotion";
import { YoshikawaProposal } from "./YoshikawaProposal";

export const Root = () => {
  return (
    <>
      <Composition
        id="YoshikawaProposal"
        component={YoshikawaProposal}
        durationInFrames={840} // 28秒 × 30fps
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
```

#### ③ src/YoshikawaProposal.tsx
```tsx
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";

// --- カーソルコンポーネント ---
// 無操作時はレンダリングされない仕様
const Cursor = ({ x, y, visible }: { x: number; y: number; visible: boolean }) => {
  if (!visible) return null;
  return (
    <svg
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: 60, // 見やすく大きめに設定
        height: 60,
        zIndex: 100,
        filter: "drop-shadow(3px 3px 5px rgba(0,0,0,0.4))",
      }}
      viewBox="0 0 320 320"
    >
      <path
        d="M 50 50 L 100 250 L 140 180 L 220 180 Z"
        fill="black"
        stroke="white"
        strokeWidth="10"
        strokeLinejoin="round"
      />
    </svg>
  );
};

// --- テキストオーバーレイコンポーネント ---
const TextOverlay = ({ text, startFrame, duration }: { text: string; startFrame: number; duration: number }) => {
  const frame = useCurrentFrame();
  
  // イーズイン・イーズアウトを伴うフェード処理
  const opacity = interpolate(
    frame,
    [startFrame, startFrame + 15, startFrame + duration - 15, startFrame + duration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) }
  );

  if (frame < startFrame || frame > startFrame + duration) return null;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", opacity, justifyContent: "center", alignItems: "center" }}>
      {text.split("\n").map((line, i) => (
        <h1 key={i} style={{ color: "white", fontSize: 64, fontWeight: "bold", margin: "10px 0" }}>
          {line}
        </h1>
      ))}
    </AbsoluteFill>
  );
};

// --- メインコンポーネント ---
export const YoshikawaProposal = () => {
  const frame = useCurrentFrame();

  // ==========================================
  // 1. ズーム（Scale & Translate Y）の計算
  // ==========================================
  // 全体表示→ズームイン→全体表示の行き来をイーズで制御
  const scale = interpolate(
    frame,
    [
      0, 40, 70,       // Scene1: 検索窓からリンクへズームイン
      80, 110,         // Scene1: HP遷移後ズームアウト
      165, 195,        // Scene2: ファーストビュー(キャッチコピー)ズームイン
      240, 269,        // Scene2: ズームアウト
      330,
      390, 420,        // Scene4: サービス一覧ズームイン
      490, 520,        // Scene4: ズームアウト
      600,
      645, 675,        // Scene6: 電話番号ズームイン
      720, 749         // Scene6: ズームアウト
    ],
    [
      1, 1, 1.4,
      1.4, 1,
      1, 1.3,
      1.3, 1,
      1,
      1, 1.3,
      1.3, 1,
      1,
      1, 1.5,
      1.5, 1
    ],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) }
  );

  // ズーム時の視点移動 (Y軸)
  const translateY = interpolate(
    frame,
    [
      0, 40, 70,       // リンク位置(少し上)へ
      80, 110,
      165, 195,        // キャッチコピー(上部)へ
      240, 269,
      330,
      390, 420,        // サービスセクションは中央維持
      490, 520,
      600,
      645, 675,        // フッター電話番号(少し下)へ
      720, 749
    ],
    [
      0, 0, 200,
      200, 0,
      0, 100,
      100, 0,
      0,
      0, 0,
      0, 0,
      0,
      0, -150,
      -150, 0
    ],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) }
  );

  // ==========================================
  // 2. カーソルの制御
  // ==========================================
  // Scene1: 検索画面でのクリック
  const showCursor1 = frame >= 30 && frame <= 65;
  const cursorX1 = interpolate(frame, [30, 50], [1200, 600], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });
  const cursorY1 = interpolate(frame, [30, 50], [800, 310], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });

  // Scene6: 電話番号のクリック
  const showCursor2 = frame >= 630 && frame <= 710;
  const cursorX2 = interpolate(frame, [630, 670], [1200, 960], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });
  const cursorY2 = interpolate(frame, [630, 670], [1000, 750], { extrapolateRight: "clamp", easing: Easing.bezier(0.25, 0.1, 0.25, 1) });

  // 現在のフレームに該当する画像を読み込み
  const frameString = String(Math.floor(frame)).padStart(5, "0");
  const imgSrc = staticFile(`frames/f_${frameString}.png`);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      
      {/* 録画フレームとズームの適用 */}
      <AbsoluteFill
        style={{
          transform: `scale(${scale}) translateY(${translateY}px)`,
          transformOrigin: "center center",
          willChange: "transform",
        }}
      >
        <Img src={imgSrc} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        
        {/* カーソル合成（ズームの影響を受けるように内側に配置） */}
        <Cursor x={cursorX1} y={cursorY1} visible={showCursor1} />
        <Cursor x={cursorX2} y={cursorY2} visible={showCursor2} />
      </AbsoluteFill>

      {/* --- テキスト挿入シーン --- */}
      <TextOverlay text="特装車のトラブル、ネットで探すお客様に選ばれるために。" startFrame={270} duration={60} />
      <TextOverlay text="専門技術と実績を、一目で伝わる形に。" startFrame={540} duration={60} />
      {/* 最後の締めはフェードアウトさせず動画終了まで表示 */}
      <TextOverlay text={"吉川特装自動車\n新しいWebサイトのご提案"} startFrame={750} duration={90} />

      {/* --- 効果音・BGM --- */}
      {/* BGM: 全体にうっすらと */}
      <Audio src={staticFile("bgm.mp3")} volume={0.15} />

      {/* タイピング音: Scene 1 最初 */}
      <Sequence from={0} durationInFrames={30}>
        <Audio src={staticFile("typing.mp3")} volume={0.5} />
      </Sequence>

      {/* クリック音1: 検索結果クリック */}
      <Sequence from={55} durationInFrames={10}>
        <Audio src={staticFile("click.mp3")} volume={0.8} />
      </Sequence>

      {/* クリック音2: 電話番号クリック */}
      <Sequence from={680} durationInFrames={10}>
        <Audio src={staticFile("click.mp3")} volume={0.8} />
      </Sequence>

    </AbsoluteFill>
  );
};
```