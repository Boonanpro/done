# Android の操作

## つなぐ

- **S24（開発用）**: Mac mini に USB で常時接続。再起動の後に見えなくなったら、まず `adb -s RFCXB0MSSTD shell settings get secure block_usb_lock` を見る（1 だとロック中に新しい USB 接続を通さない。10/25 に本人承認で 0 にした。更新で戻ることがある。`dumpsys usb` の SettingBlockUsbLock でも見える）。USB デバッグには Samsung の「自動ブロッカー」オフが要る（オフのまま維持）。
- **S25（本人）**: 本人が無線デバッグをオンにすれば、保存済みのペアリングでつながる。IP やペアリングコードを先に聞かず、`adb devices` と `adb mdns services` から再接続する（ポートは毎回変わる）。
- 2026-10-23 より前の記録は Windows の adb（`C:\Users\Owner\AppData\Local\Android\Sdk\platform-tools\adb.exe`）の話。今は Mac mini の Homebrew の adb を使う。

## ロックを開ける

- `phone` 道具は自分でロックを開ける（解除後30秒は確認を省く）。
- 手で開ける時は PIN を画面に出さない道具を使う: `/Users/mikihonda/dan-workspace/bin/phone_unlock.py`。PIN は `get_credentials(service="galaxy_s24_dev")`。ロック状態は `dumpsys window | grep isKeyguardShowing`。

## 画面を読んで押す（phone 道具）

- 操作は `phone` 道具で行う: `read`（部品一覧、`query` で絞る）→ `tap`（ref か label）/ `type` / `scroll` / `key` / `open`（package 名）/ `screenshot` / `follow`（押すだけで goal まで進む。入力・購入・送信はしない）。1回の呼び出しで押した後の画面が返るので、毎回それを読んで次を決める。
- 購入・送信・削除・確定は、本人がその操作を承認した時だけ `confirmed=true` で押す。
- 押した手順は自動で記憶され、flow で再生できる（穴の値は依頼から渡す）。
- **自分で `uiautomator dump` や uiautomator2 を動かさない。** 動いている間、端末の全ユーザー補助（ポルノブロッカーの見張り・Samsung の補助）が止まる。phone 道具はこれを避ける設定で動いている。古いサーバーが残っていたら `adb shell pkill -f uia2`。
- 使い終わって90秒で端末の押さえが外れる。

### 押しても効かない時

- 透明な画面が上に乗っていることがある（`com.android.companiondevicemanager` の CompanionAssociationActivity、ピンの組み付け）。BACK で閉じる。
- 設定アプリでは、スクロール中の古い位置を押すことがある。スクリーンショットを撮り直して位置を確かめる。
- LINE は部品が取れない画面がある。スクリーンショットの位置で押す（表示座標×1.17 が実座標）。
- 銀行アプリ（楽天銀行など）は画面の取得が真っ黒になる。操作できないので同じ試行を繰り返さない。

### 文字を入れる

- `adb shell input text` は英数字だけ。日本語は phone の `type` を使う（Google アカウントを入れた S24 では、貼り付けで入れる方式に自動で切り替わる）。
- 認証情報は画面に出さずに入れる: `/Users/mikihonda/dan-workspace/s24-x/phone_cred.py <service> username|password|totp [enter]`。

## アプリを入れる

- **Done アプリ（Mac で組み立て）**: `cd /Users/mikihonda/done/mobile && npm ci && npx expo prebuild --platform android --no-install --clean` → `android/gradle.properties` の jvmargs を `-Xmx6144m -XX:MaxMetaspaceSize=2048m` に上げる（上げないと落ちる）→ `./gradlew :app:assembleRelease -PreactNativeArchitectures=arm64-v8a`。版は `app.json` の version と versionCode を両方上げる。出力は `/Users/mikihonda/done/scratch/Done-<版>.apk`、配布は `mobile/scripts/publish_apk.py`。新しいネイティブ部品を足した版は OTA で届かない。詳細は記憶 reference-mac-android-build。
- S24 への転送で `adb install -r` が止まったら、`adb push` → `adb shell pm install` に切り替える。
- **ポルノブロッカー（dev.dan.safeguard）**: 入れ替えは `tools/install_verified.py`（serial 必須。ユーザー補助を保ったまま入れ、見張りの接続と VPN まで確かめる）。端末に更新を今すぐ確かめさせる: `am broadcast -a dev.dan.pornblocker.CHECK_UPDATE -n dev.dan.safeguard/dev.dan.pornblocker.UpdateNowReceiver`。更新が届かない時は `appops get dev.dan.safeguard REQUEST_INSTALL_PACKAGES` を見る（deny なら allow に）。
- `am force-stop dev.dan.safeguard` はしない（ユーザー補助の登録が消える）。止める時は `pm disable-user`、戻す時は `pm enable` → ユーザー補助を入れ直す → `dpm set-active-admin` → アプリで遮断をオン。
- Play ストアに無い経路で LINE・X を入れる時は、APKMirror の分割版を落とし、`apksigner` で配布元の署名を確かめてから `adb install-multiple`。自動更新されない。

## 設定画面で覚えたこと

- S24 の本人好み: 画面消灯10分、充電中も点けっぱなしにしない（`stay_on_while_plugged_in=0`）、おやすみモード、サイレント、タッチの振動オフ。試験の間だけ外し、終わったら戻す。
- ナビゲーションの方式は adb の settings 書き換えでは反映されない。設定画面で選ぶ。
- 大きな更新の後は「ようこそ One UI」が出る。Samsung アカウントは「後で設定」で飛ばす。
- VPN の常時接続のスイッチはユーザー補助から見えない。本人に押してもらう。
- 2本指の操作は `sendevent` が使えない。`app_process` で `injectInputEvent` を使う道具が `pornblock-gesture-20261030/tool` にある。

## スマホでのログイン

- **S24 の LINE**: ログインは必ず「サブ端末」を選ぶ（「メイン端末」は本人の S25 をログアウトさせる）。QR は30秒で切れるので `s24-line/qr_loop.py` で更新し続け、ログインしたらすぐ止める。LINE で届いたファイルは `/sdcard/Android/data/jp.naver.line.android/files/chats/` から `adb pull`。
- **S24 の X**: @PornoAnti_JP（credentials `x_pornblock`、メールの確認コード方式）。研究用ブラウザで検索を連打すると制限がかかり、S24 の X まで止まった。

## 画面を録画する

- `adb screenrecord` は1本180秒まで。続けて録る道具: `pornanti_line_video_20261020/footage_20261026/_work/rec.py`（縦1080×2340、指の点つき）。adb input で押した所には指の点が出ない。
- S24 の録画は画面が変わった時だけコマが入る。`ffmpeg -ss` で切り出すと最大15秒ずれるので、コマの時刻を読んで切る。
- 通話の試験では、Mac から `say -v Kyoko` で話しかけるとスマホが聞き取る。電話の発信は試験でもしない。

## その他

- ポルノブロッカーの VPN がオンの間、Done アプリは「Connection unavailable」になる。
- 長い試験で端末が熱くなると判定が遅くなる（`dumpsys thermalservice`）。
- 再起動すると logcat は消える。調べたい記録は再起動の前に取る。
