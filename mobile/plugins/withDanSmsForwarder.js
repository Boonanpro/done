const { AndroidConfig, withAndroidManifest, withDangerousMod, withMainApplication } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const PACKAGE_PATH = ['app', 'done', 'dan', 'sms'];

function writeNativeSources(projectRoot) {
  const dir = path.join(projectRoot, 'android', 'app', 'src', 'main', 'java', ...PACKAGE_PATH);
  fs.mkdirSync(dir, { recursive: true });

  fs.writeFileSync(path.join(dir, 'DanSmsForwarderModule.kt'), `package app.done.dan.sms

import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class DanSmsForwarderModule(private val context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {
  override fun getName() = "DanSmsForwarder"

  @ReactMethod
  fun configure(apiBaseUrl: String, deviceToken: String, promise: Promise) {
    context.getSharedPreferences(DanSmsForwarderReceiver.PREFS, 0).edit()
      .putString("apiBaseUrl", apiBaseUrl.trimEnd('/'))
      .putString("deviceToken", deviceToken)
      .putBoolean("enabled", true)
      .apply()
    promise.resolve(true)
  }

  @ReactMethod
  fun disable(promise: Promise) {
    context.getSharedPreferences(DanSmsForwarderReceiver.PREFS, 0).edit().clear().apply()
    promise.resolve(true)
  }

  @ReactMethod
  fun isEnabled(promise: Promise) {
    val enabled = context.getSharedPreferences(DanSmsForwarderReceiver.PREFS, 0)
      .getBoolean("enabled", false)
    promise.resolve(enabled)
  }
}
`);

  fs.writeFileSync(path.join(dir, 'DanSmsForwarderPackage.kt'), `package app.done.dan.sms

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.uimanager.ViewManager

class DanSmsForwarderPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> =
    listOf(DanSmsForwarderModule(context))

  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> =
    emptyList()
}
`);

  fs.writeFileSync(path.join(dir, 'DanSmsForwarderReceiver.kt'), `package app.done.dan.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class DanSmsForwarderReceiver : BroadcastReceiver() {
  companion object {
    const val PREFS = "danSmsForwarder"
  }

  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
    val prefs = context.getSharedPreferences(PREFS, 0)
    if (!prefs.getBoolean("enabled", false)) return
    val apiBaseUrl = prefs.getString("apiBaseUrl", null) ?: return
    val deviceToken = prefs.getString("deviceToken", null) ?: return
    val pending = goAsync()

    Thread {
      try {
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        val sender = messages.firstOrNull()?.displayOriginatingAddress ?: ""
        val body = messages.joinToString("") { it.displayMessageBody ?: "" }
        if (!Regex("""\\b\\d{4,8}\\b""").containsMatchIn(body)) return@Thread
        val payload = JSONObject()
          .put("sender", sender)
          .put("body", body)
          .put("message_id", messages.firstOrNull()?.timestampMillis?.toString())
        val connection = URL("$apiBaseUrl/api/v1/otp/apk/forward").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 10000
        connection.readTimeout = 10000
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        connection.setRequestProperty("X-Dan-Otp-Device-Token", deviceToken)
        connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
        connection.inputStream.use { it.readBytes() }
        connection.disconnect()
      } catch (_: Exception) {
        // OTP remains available on the phone for manual entry.
      } finally {
        pending.finish()
      }
    }.start()
  }
}
`);
}

module.exports = function withDanSmsForwarder(config) {
  config = withAndroidManifest(config, (mod) => {
    const manifest = mod.modResults.manifest;
    AndroidConfig.Permissions.ensurePermissions(mod.modResults, [
      'android.permission.RECEIVE_SMS',
      'android.permission.INTERNET',
    ]);
    const application = AndroidConfig.Manifest.getMainApplicationOrThrow(mod.modResults);
    application.receiver = application.receiver || [];
    if (!application.receiver.some((item) => item.$['android:name'] === 'app.done.dan.sms.DanSmsForwarderReceiver')) {
      application.receiver.push({
        $: {
          'android:name': 'app.done.dan.sms.DanSmsForwarderReceiver',
          'android:enabled': 'true',
          'android:exported': 'true',
          'android:permission': 'android.permission.BROADCAST_SMS',
        },
        'intent-filter': [{
          action: [{ $: { 'android:name': 'android.provider.Telephony.SMS_RECEIVED' } }],
        }],
      });
    }
    return mod;
  });

  config = withMainApplication(config, (mod) => {
    let src = mod.modResults.contents;
    if (!src.includes('app.done.dan.sms.DanSmsForwarderPackage')) {
      src = src.replace(
        /package app\.done\.dan\s*/,
        'package app.done.dan\n\nimport app.done.dan.sms.DanSmsForwarderPackage\n',
      );
      src = src.replace(
        /PackageList\(this\)\.packages\.apply \{/,
        'PackageList(this).packages.apply {\n              add(DanSmsForwarderPackage())',
      );
    }
    mod.modResults.contents = src;
    return mod;
  });

  return withDangerousMod(config, ['android', async (mod) => {
    writeNativeSources(mod.modRequest.projectRoot);
    return mod;
  }]);
};
