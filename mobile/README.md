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

アプリは `App.tsx` の `API_BASE_URL` で指定されたDAN本番APIに接続します。
