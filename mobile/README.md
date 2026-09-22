# DAN Mobile

Expo/React Native版のDANアプリです。

## 開発中にスマホで開く

```powershell
cd D:\done\mobile
npm start
```

Android/iPhoneにExpo Goを入れて、表示されたQRコードを読み取ります。

## Android Development Buildを作る

ネイティブ機能の開発に使うDAN専用アプリです。

```powershell
cd D:\done\mobile
npx eas-cli login
npx eas-cli build --platform android --profile development
```

ビルド完了後に表示されるURLからAPKをダウンロードしてAndroidへインストールできます。
インストール後は、開発サーバーを起動してDANアプリから接続します。

```powershell
cd D:\done\mobile
npm start
```

## Android Preview APKを作る

EASにログインした状態で実行します。

```powershell
cd D:\done\mobile
npx eas build --platform android --profile preview
```

ビルド完了後に表示されるURLからAPKをダウンロードしてAndroidへインストールできます。

## 接続先

アプリは `https://dan.paina.info` の固定トンネルへ接続します。
`app.json` の `extra.apiBaseUrl` と `App.tsx` の既定値を揃えています。
1.0.5 (Android versionCode 3) からこの接続先を使用します。
runtimeVersion は appVersion に連動し、旧1.0.4の配信更新が新APKの接続先を
戻さないようにしています。PCのDanサーバーは起動している必要があります。

## 接続したAndroid端末へローカルAPKを更新する

### 外出・Bluetoothイヤホン試験（1.0.6 / versionCode 4）

Galaxy側で通話対応のBluetoothイヤホンをペアリングし、Danアプリの音声を開始します。
初回は「付近のデバイス」を許可してください。スピーカー固定を解除し、通話の自動
経路選択に変更しました。音量はスマホの通話音量で調整します。8倍の追加増幅は撤去しました。
イヤホンなしでは受話口を使います。Bluetooth権限を拒否しても本体で開始できます。

接続先は固定HTTPSなので、モバイルデータでの利用にTailscaleは不要です。
自宅DanのPCは起動しておく必要があります。このAPKはAtomの中継機能を持ちません。
1.0.7はLive 1＋Astraへ移行しました。部屋の履歴、司令塔ツール、追加指示、音声での通話終了を接続しています。
Bluetooth双方向音声は1.0.6でユーザー確認済み。1.0.7ではGalaxy実機のLive接続と挨拶、閉じる操作後の通話モード解除を確認しました。
1.0.7での自然な会話・音声終了の実機再テスト、LE Audio・画面オフ・着信時の動作確認は残っています。
1.0.8はAndroidのマイク用フォアグラウンドサービスと通知の終了ボタンを追加しました。
通話開始後はホーム画面へ戻ったり画面を消したりできます。画面オフで止まるJSタイマーを補うため、
Androidからの定期通知で文字起こしの確定・終了判定・作業状態取得を動かします。
アプリの強制停止やタスク削除後に通話を自動再開する仕様ではありません。
設計と実機確認項目は `../docs/current/outdoor-voice-20260916.md` を参照してください。

1.0.9はDoneの相談窓口とプロジェクト一覧を分け、検索と直接の音声開始を追加しました。
通話画面は最小化でき、他の部屋へ移動しても通話先は開始時の部屋を維持します。
Atomと同じ2音の接続・待機音、ミュート、経過時間を追加しました。
Galaxy実機で、アプリ外の画面上部に緑色の通話時間表示、通知からの終了、
終了音の再生完了とマイク・通話モードの解除まで確認済みです。
Androidの通話通知は無音のIMPORTANCE_DEFAULTチャネルを使用します。
接続音はLive接続後に再生し、その後にAIの挨拶を要求します。

APK更新時はruntimeVersionも更新し、旧APK用のOTA更新が試験コードを上書きしないようにしています。

### ビルドとインストール

Android SDKとJDKを設定したPowerShellで実行します。

```powershell
cd D:\done\mobile
$env:NODE_ENV = 'production'
npx expo prebuild --platform android --no-install
cd android
.\gradlew.bat :app:assembleRelease -PreactNativeArchitectures=arm64-v8a --max-workers=4 --console=plain
adb install -r app\build\outputs\apk\release\app-release.apk
```

上書き更新には既存アプリと同じ署名が必要です。署名不一致時にアンインストール
して回避するとアプリデータを失うため、元の署名鍵でビルドしてください。
