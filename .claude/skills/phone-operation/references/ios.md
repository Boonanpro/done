# iPhone の操作

iPhone は Android と違い、Mac から自由に押せる仕組みが無い。使えるのは「開発中のアプリを試す仕組み（XCTest）」だけで、これを1手ずつ動く形にしないと、押す順番を全部書いて毎回1〜2分かけて流し直すことになる。2026-11-01 の借りた iPhone ではこれで X のログインに30分近くかかった（確認コードの画面に気づけず、コード欄にメールアドレスを打とうとして約250秒固まった）。

## つないだら最初にやること（この順で）

1. **端末を確かめる**: `xcrun devicectl list devices`（UDID・機種・connected）。Mac の Xcode は `/Applications/Xcode.app`（`export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`）。
2. **触る前に控える**: アプリ一覧（`xcrun devicectl device info apps --device <UDID>` を evidence に保存）、自動ロックの今の時間（本人に聞く）、変える予定の設定の今の値。
3. **本人の手が要る物を1回でまとめて頼む**:
   - Xcode に本人の Apple Account でログイン（Mac 画面上部の「Xcode」→ Settings → Accounts → ＋）。2026-11-01 時点の Personal Team は `27R5T843GT`。無料の署名は7日で切れる。
   - デベロッパモードをオン（設定 → プライバシーとセキュリティ → デベロッパモード、再起動あり）。項目が無い時は `pymobiledevice3` の reveal-developer-mode で出す。
   - アプリを入れた後、設定 → 一般 → VPNとデバイス管理 → デベロッパApp で「信頼」。
   - 最初の XCTest の時に iPhone に出る「UI自動操作のためのパスコード入力」。
   - 自動ロックを「なし」（試験中に画面が消えるとロック解除が要る）。
   - ロックの解除。iPhone はパスコードを知っていても Mac からは開けない。画面を触れるのは本人だけ。
4. **画面を見られるようにする**: `pornblock-ios-20261101/tools/ioscap`（QuickTime と同じ経路で USB の画面を録る。`ioscap --list` で見えるか、`IOSCap.app` から `open -n tools/IOSCap.app --args <out.mov> <秒>` で録る。カメラの許可のため .app に包んである）。
5. **1手ずつ押せる操作役を立てる**: まだ作っていない（2026-11-01 時点）。次の iPhone で本題の前に作り、1手1秒前後で「押す・打つ・画面写真・部品一覧」が返ることを確かめる。第一候補は WebDriverAgent（Appium の iPhone 操作役。常駐した XCTest が HTTP で命令を受ける）。動かなければ `UITests/DriveTests.swift` を「命令をファイルから読み、押して、画面写真と部品一覧を書き出す」を繰り返す常駐のテストに作り替える。押す順番を全部書いた XCTest を毎回ビルドして流す形には戻さない。

## 試作アプリを入れる・動かす

作業場所 `/Users/mikihonda/dan-workspace/pornblock-ios-20261101`（README に経緯）。

- 組み立てと導入: `xcodebuild -project SafeguardIOS.xcodeproj -scheme SafeguardIOS -destination id=<UDID> -derivedDataPath DerivedData -allowProvisioningUpdates -allowProvisioningDeviceRegistration DEVELOPMENT_TEAM=27R5T843GT build`
- テストで動かす: `xcodebuild test-without-building ... DEVELOPMENT_TEAM=27R5T843GT CODE_SIGN_STYLE=Automatic -only-testing:<対象> -resultBundlePath evidence/<名前>.xcresult`。撮った画面は `xcrun xcresulttool export attachments --path <xcresult> --output-path <dir>`。
- 起動: `xcrun devicectl device process launch --device <UDID> <bundle id>`。ロック中は起動しても画面は黒い。
- アプリのデータを取り出す: `xcrun devicectl device copy from --device <UDID> --domain-type appDataContainer --domain-identifier <bundle id> --source Documents/sg.log --destination <手元>`。
- 消す: `xcrun devicectl device uninstall app --device <UDID> <bundle id>`。UI テストの操作役（`<bundle id>.uitests.xctrunner`）も消す。

## 覚えたこと

- **X のログイン**: 初めての端末では、パスワードの前にメールの確認コードが出る。コードは `lookup` で受信箱から読む。ポルノアンチ用のアカウントでよいと本人が言っている（2026-11-01）。認証情報はテストへ環境変数（`TEST_RUNNER_` で始まる名前）で渡し、ファイルに書かない。
- **アプリ内ブラウザ（WKWebView）で X が白い画面になる**: X が `x-safari-https://redirect.x.com` で Safari へ移ろうとする。`applicationNameForUserAgent` を Mobile Safari 相当にすると X のページが出る。
- **XCTest の固まり**: 存在しない欄に文字を打とうとすると「Check for interrupting elements」で数分固まる。打つ前に欄の存在を短い待ちで確かめる。
- **設定画面の撮影**: スクリーンタイムの設定操作は設定アプリ（`com.apple.Preferences`）を XCTest で押して撮れた（`UITests/SettingsTests.swift`）。撮影素材の例: `pornanti_line_video_20261020/footage_20261026/07_iphone_screentime_settings.mov`。
- **iPhone の写真・動画の判定**: アプリ内の保護付きブラウザ・保護付きXの中だけで判定できる。Xの公式アプリの中身は iPhone の仕組み上見られない。

## 返す前（借りた iPhone）

1. ダンが入れたアプリと UI テストの操作役を消し、アプリ一覧から消えたことを確かめる。
2. 変えた設定（スクリーンタイムの制限など）を控えた値に戻す。
3. 本人に1回で渡す: デベロッパモードのオフ（再起動あり）、自動ロックを控えた時間へ。
4. Mac 側の録画と操作の処理が止まっていることを確かめる（`pgrep -fl -i "IOSCap|xcodebuild|xctest"`）。
5. 「このコンピュータを信頼」の記録は残るが、害は無い。
