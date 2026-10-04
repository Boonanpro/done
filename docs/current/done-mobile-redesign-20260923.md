# Done APK 1.0.28：採用ホームの実装

2026-09-23。ユーザーが選んだホーム構成をReact Nativeへ実装。

## 実装

- Done表記。ホームは上にマイクとチャットのアイコン、下に固定カード1枚。ホーム自体にScrollViewを使わない。
- カードはサーバーの `has_active_run` と端末から送信中のプロジェクトを表示。スワイプ・左右ボタン・ページ位置ボタンで内容だけを変更。未読を作業中と見なさない。選択中のIDを保持し、一覧順の変化で勝手に他の部屋へ切り替えない。
- 0件は `No active rooms`。0件でも更新ボタンを提供。進捗率や作業内容は推測で作らず、部屋名と実行状態を表示する。
- Projectsに検索・履歴・未読・ピン・新規・削除・共同ルームへの入口を集約。長押し以外に明示的なメニューを提供。
- Libraryはプロジェクトを選んで成果物を取得。プロジェクトごとの既存APIと登録URLを使用。全プロジェクトへの並列取得は行わない。
- 英語既定。Settingsから日本語に変更してSecureStoreへ保存。名称・会話本文・成果物は翻訳しない。端末のOS言語は変更しない。
- ホーム、会話、設定を明るい白とグリーンに統一。チャットは全幅入力欄と操作列の二段構成。送信は矢印、停止は四角のアイコン。読み上げ用の名前を保持。
- AtomはSettingsへ移動。ホームのマイクは既存の全体相談部屋で直接開始する。VoiceHostと通信・認証・送信ロジックを維持。

主なソース：`mobile/done-dashboard.tsx`、`dashboard-state.ts`、`ui-language.ts`、`App.tsx`。`voice.tsx`、`voice-host.tsx`、`atom-relay-control.tsx`、`collab.tsx`の表示文言をローカライズ。

## 検証

- TypeScript成功。
- `node mobile/scripts/test-dashboard-state.cjs`：サーバーとローカルの実行中判定、未読の除外、並び替えと選択ID、削除、切替境界、横/縦スワイプ判別を確認。
- arm64-v8a / x86_64のReleaseビルド成功。アプリ・Android・Expo runtimeを1.0.28、versionCodeを27に統一。
- Galaxy SM-S931Qへ同一署名で上書きインストール。ログインと会話履歴保持、英語ホーム、日英の切替、英語設定の再起動後保持、ホームの一画面収まりを実機確認。
- 実機でチャットの描画、IME表示時の入力欄と送信領域、Projects一覧、Libraryの部屋選択と制作物0件表示、ホームへ戻る操作を確認。
- ユーザー端末でメッセージ送信・音声通話開始・プロジェクト作成/削除は行っていない。

実機では作業中の部屋が0件だったため、複数の実行中部屋のスワイプはネイティブ実機で未再現。切替ロジックのテストとブラウザ試作の操作検証とは区別する。Bluetooth、通話継続、TalkBack読み上げ、実送信の回帰確認は今回未実施。会話本文やバックエンドから返る文章、Android自身の文言はUI言語切替で翻訳しない。

## 配布

APK：`scratch/done-native-redesign/Done-1.0.28.apk`。
実機画像/XML：`scratch/done-native-redesign/`。`final-home.png`、`chat.png`、`keyboard.png`、`settings-ja.png`、`delivered-projects.png`、`library-files.png`。
ビルドログ：`scratch/done-native-redesign/build.log`。

この変更はAPKのローカル配布。PCブラウザ3000や制作エディターの再配信は行っていない。Gitへのコミット・pushなし。他セッションの未コミット作業を保持。
# 追記：1.0.29 タブ改訂

配布：接続端末 RFCY205CPNM に versionName 1.0.29 / versionCode 28 をインストール済み。英語表示に戻し、Collab一覧を開いて納品。実機で日英のタブ、実データ一覧、プロフィール画面、作成フォームの空欄抑止・文字入力・キーボード表示、フォームから一覧へのシステムBackを確認。一時的な一覧取得失敗は再試行で復旧。画面証跡は `scratch/done-native-redesign/release29-*.png`、配布APKは `scratch/done-tabs-release/Done-1.0.29.apk`。

Home / Projects / Collab に変更。独立した制作物タブを削除し、Doneロゴと設定ボタンはHomeだけに表示。Projectsの「Pick up where you left off」を削除。プロジェクト内の成果物は既存経路を維持。

Collab一覧は右上に新規作成の＋とプロフィールの人物アイコンを配置。ルーム名・最新メッセージの2行を維持し、行の最小高76、上下余白12、アバター40に圧縮。実際の `/collab/rooms` 作成APIと `/chat/profile` 保存APIを使用。入力が空の場合と処理中の二重送信を抑止し、失敗時は入力を残す。部屋作成は招待・メッセージの送信を行わない。

検証：TypeScript、ホーム状態テスト、コラボ作成/プロフィールのAPI引数・入力保持・二重送信抑止・再試行のモックテストが成功。リリースビルド成功。実際の新規ルーム作成やプロフィール変更はテスト目的で実行していない。
