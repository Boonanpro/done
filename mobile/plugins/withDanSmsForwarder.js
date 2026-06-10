const { AndroidConfig, withAndroidManifest, withAppBuildGradle, withDangerousMod, withMainApplication } = require('@expo/config-plugins');
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
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import java.util.concurrent.TimeUnit

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
    val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
    val sender = messages.firstOrNull()?.displayOriginatingAddress ?: ""
    val body = messages.joinToString("") { it.displayMessageBody ?: "" }
    if (!Regex("""\\b\\d{4,8}\\b""").containsMatchIn(body)) return

    // Hand the POST to WorkManager: a one-shot fire-and-forget request loses the
    // code forever on any transient network/server failure, and OTPs cannot be
    // re-fetched. WorkManager retries with backoff and survives process death.
    val request = OneTimeWorkRequestBuilder<DanSmsForwardWorker>()
      .setConstraints(
        Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
      )
      .setBackoffCriteria(BackoffPolicy.LINEAR, 30, TimeUnit.SECONDS)
      .setInputData(
        workDataOf(
          "apiBaseUrl" to apiBaseUrl,
          "deviceToken" to deviceToken,
          "sender" to sender,
          "body" to body,
          "messageId" to (messages.firstOrNull()?.timestampMillis?.toString() ?: ""),
        )
      )
      .build()
    WorkManager.getInstance(context).enqueue(request)
  }
}
`);

  fs.writeFileSync(path.join(dir, 'DanSmsForwardWorker.kt'), `package app.done.dan.sms

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class DanSmsForwardWorker(context: Context, params: WorkerParameters) :
  Worker(context, params) {
  override fun doWork(): Result {
    // OTPs expire in ~10 minutes; with linear 30s backoff, attempt 6 lands past
    // that window, so further retries would only deliver dead codes.
    if (runAttemptCount >= 6) return Result.failure()
    val apiBaseUrl = inputData.getString("apiBaseUrl") ?: return Result.failure()
    val deviceToken = inputData.getString("deviceToken") ?: return Result.failure()
    val payload = JSONObject()
      .put("sender", inputData.getString("sender") ?: "")
      .put("body", inputData.getString("body") ?: "")
      .put("message_id", inputData.getString("messageId") ?: "")
    return try {
      val connection = URL("$apiBaseUrl/api/v1/otp/apk/forward").openConnection() as HttpURLConnection
      connection.requestMethod = "POST"
      connection.connectTimeout = 10000
      connection.readTimeout = 15000
      connection.doOutput = true
      connection.setRequestProperty("Content-Type", "application/json")
      connection.setRequestProperty("X-Dan-Otp-Device-Token", deviceToken)
      connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
      val code = connection.responseCode
      connection.disconnect()
      when {
        code in 200..299 -> Result.success()
        code == 401 -> Result.failure() // token revoked — retrying cannot help
        else -> Result.retry()
      }
    } catch (_: Exception) {
      Result.retry()
    }
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

  config = withAppBuildGradle(config, (mod) => {
    if (!mod.modResults.contents.includes('androidx.work:work-runtime')) {
      mod.modResults.contents = mod.modResults.contents.replace(
        /dependencies\s*\{/,
        'dependencies {\n    implementation("androidx.work:work-runtime-ktx:2.9.1")',
      );
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
