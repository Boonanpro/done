# 専用検証環境の予算見直し（2026-09-21）

前日の最新機種中心の約50万円案を、用途から見直した。購入は行っていない。

## 推奨構成

現WindowsはDanの既存実行環境として維持し、専用Macへスマホ2台を接続する。Macはビルド・端末操作・ブラウザ・試験を担当。Windowsの実装をすべてMacへ即移植する計画ではない。

|品目|必要十分と判断する仕様|確認価格／予算|
|---|---|---:|
|中古Mac mini|M2（2023）、16GB、SSD256GB。ログ・録音は外付けへ|64,000円の掲載あり|
|中古Galaxy S24|国内版、8GB/256GB、通常モデル|62,800円、中古B|
|中古iPhone 13|128GB、SIMフリー、バッテリー状態確認|47,800円、中古B|
|周辺機器|給電対応データハブ、データケーブル、固定具、必要な録音／再生機材、外付けSSD等|20,000〜30,000円の予算枠|
|合計|掲載価格3台174,600円＋周辺機器|194,600〜204,600円、送料等別|

Mac掲載のMMFK3J/AとSSD256GB表記には整合確認が必要。注文前に実個体のメモリ／SSDを確認する。1台在庫のため価格・在庫は固定保証ではない。M2 16GBを6〜8万円で探す予算なら全体約19〜22万円。

モニター・キーボード・マウス・イヤホンは既存品流用が基本。専用に追加すれば別費用。SIM、API、開発者登録費は含まない。

## Windows案

Android・Windows操作を優先するならWindows 11 x64、Core i5第12世代またはRyzen 5 6600H級、16GB、SSD512GB。実機中心の検証で16GB、複数ビルド／仮想端末を同時実行するなら32GB。高性能GPU不要。

GMKtec M8 Ryzen 5 PRO 6650H /16GB/512GBの公式表示58,599円。Galaxy S24と周辺機器1〜2万円で131,399〜141,399円。iPhoneの本格的なローカル自動検証には別途Mac環境が必要。

既存Windows＋専用S24のみなら62,800円＋周辺機器予算5,000〜10,000円＝67,800〜72,800円。ただしPC操作環境の完全分離は実現しない。

## 選定理由と限界

- S24の7世代OS／7年セキュリティ更新、普段のS25に近いSamsung環境を優先。S23以前でも性能不足とは限らないが、今購入する主検証端末としてS24を推奨。
- iPhone 13は基本的な音声・Bluetooth・バックグラウンド・UI検証に十分と判断。最新機種限定機能の検証はカバーしない。
- Mac M1 16GBでも候補になるが、今購入するなら2023年M2を基準にする。これは性能／価格／残るOS対応のバランスによる推奨で、M1では動かないという意味ではない。
- Xcode・Appium・端末OSの互換性は導入時に揃える。Mac購入だけで無人の全操作・ログイン・権限確認まで自動化できるわけではない。
- メーカーが異なるAndroid全機種や、あらゆるBluetooth機器の挙動を1台で保証はできない。

## 確認先

- Mac M2 16GB、64,000円、在庫1：https://www.mac-paradise.com/htmls/1100000267843-21.html
- Galaxy S24：https://iosys.co.jp/items/smartphone/galaxy/galaxy_s24
- iPhone 13：https://www.iosys.co.jp/items/smartphone/iphone/iphone13?not=pro&page=2
- Windows PC：https://jp.gmktec.com/products/gmktec-m8-amd-ryzen-5-pro-6650h-mini-pc
- Samsung更新方針：https://www.samsungmobilepress.com/articles/enter-the-new-era-of-mobile-ai-with-samsung-galaxy-s24-series
- iOS対応端末：https://support.apple.com/guide/iphone/iphone-models-compatible-with-ios-27-iphe3fa5df43/27/ios/27
- Android Studio必要環境：https://developer.android.com/studio/install.html
- Xcode必要環境：https://developer.apple.com/xcode/system-requirements
- iOS自動操作の要件：https://appium.github.io/appium-xcuitest-driver/latest/installation/requirements/
