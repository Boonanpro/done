// アプリの更新をボタン1つにする（2026-10-24）。本人「とりあえずインストールを押すやつで良いわ。いちいちUSB繋いでデバックするよりはまし。
// ただどこから押せばいいのか分からないのでそれは分かりやすくしてほしい」。
//
// アプリが新しい APK を落とした後、Android のインストール画面を開くための小さな部品 DanAppUpdate を足す:
//   info()                入っている版（versionName・versionCode）
//   canInstall()          この提供元からの APK のインストールが許されているか（初めての時は Android の設定で許す）
//   openInstallSettings() その設定の画面（「この提供元のアプリを許可」）を開く
//   install(contentUri)   expo-file-system の content:// URI の APK で、インストールの画面を開く
// 使う側は mobile/app-update.tsx。REQUEST_INSTALL_PACKAGES が要るので、この部品を入れる版だけはファイルから入れる。
const { AndroidConfig, withAndroidManifest, withDangerousMod, withMainApplication } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const MODULE = `package app.done.dan.update

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager

class DanAppUpdateModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  override fun getName() = "DanAppUpdate"

  @ReactMethod
  fun info(promise: Promise) {
    try {
      val pm = context.packageManager
      val pkg = if (Build.VERSION.SDK_INT >= 33) pm.getPackageInfo(context.packageName, android.content.pm.PackageManager.PackageInfoFlags.of(0))
        else @Suppress("DEPRECATION") pm.getPackageInfo(context.packageName, 0)
      val code = if (Build.VERSION.SDK_INT >= 28) pkg.longVersionCode.toDouble() else @Suppress("DEPRECATION") pkg.versionCode.toDouble()
      val out = Arguments.createMap()
      out.putString("versionName", pkg.versionName ?: "")
      out.putDouble("versionCode", code)
      promise.resolve(out)
    } catch (e: Exception) {
      promise.reject("info", e)
    }
  }

  @ReactMethod
  fun canInstall(promise: Promise) {
    promise.resolve(if (Build.VERSION.SDK_INT >= 26) context.packageManager.canRequestPackageInstalls() else true)
  }

  @ReactMethod
  fun openInstallSettings(promise: Promise) {
    try {
      val intent = if (Build.VERSION.SDK_INT >= 26)
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + context.packageName))
      else Intent(Settings.ACTION_SECURITY_SETTINGS)
      intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
      promise.resolve(true)
    } catch (e: Exception) {
      promise.reject("settings", e)
    }
  }

  @ReactMethod
  fun install(contentUri: String, promise: Promise) {
    try {
      val intent = Intent(Intent.ACTION_VIEW)
      intent.setDataAndType(Uri.parse(contentUri), "application/vnd.android.package-archive")
      intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
      promise.resolve(true)
    } catch (e: Exception) {
      promise.reject("install", e)
    }
  }
}

class DanAppUpdatePackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(DanAppUpdateModule(context))
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}
`;

module.exports = function withDanAppUpdate(config) {
  config = withAndroidManifest(config, (mod) => {
    AndroidConfig.Permissions.ensurePermissions(mod.modResults, ['android.permission.REQUEST_INSTALL_PACKAGES']);
    return mod;
  });
  config = withMainApplication(config, (mod) => {
    if (!mod.modResults.contents.includes('add(app.done.dan.update.DanAppUpdatePackage())')) {
      mod.modResults.contents = mod.modResults.contents.replace(
        /PackageList\(this\)\.packages\.apply \{/,
        '$&\n              add(app.done.dan.update.DanAppUpdatePackage())',
      );
    }
    return mod;
  });
  return withDangerousMod(config, ['android', async (mod) => {
    const dir = path.join(mod.modRequest.projectRoot, 'android', 'app', 'src', 'main', 'java', 'app', 'done', 'dan', 'update');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'DanAppUpdateModule.kt'), MODULE);
    return mod;
  }]);
};
