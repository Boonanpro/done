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

  fs.writeFileSync(path.join(dir, 'DanSmsForwarderSender.kt'), `package app.done.dan.sms

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

enum class ForwardResult { SUCCESS, AUTH_FAILED, RETRY }

object DanSmsForwarderSender {
  const val CHANNEL_ID = "dan_sms_forward"

  /**
   * POST one SMS to the server.
   *
   * connectMs/readMs are caller-supplied because the two call sites have very
   * different budgets: the BroadcastReceiver must finish everything within the
   * system's ~10s broadcast limit, while the WorkManager fallback can afford to
   * wait. Reusing the worker's generous timeouts inside the receiver would blow
   * that limit and get the app killed.
   */
  fun post(
    apiBaseUrl: String,
    deviceToken: String,
    sender: String,
    body: String,
    messageId: String,
    connectMs: Int,
    readMs: Int,
  ): ForwardResult {
    return try {
      val payload = JSONObject()
        .put("sender", sender)
        .put("body", body)
        .put("message_id", messageId)
      val url = apiBaseUrl.trimEnd('/') + "/api/v1/otp/apk/forward"
      val connection = URL(url).openConnection() as HttpURLConnection
      connection.requestMethod = "POST"
      connection.connectTimeout = connectMs
      connection.readTimeout = readMs
      connection.doOutput = true
      connection.setRequestProperty("Content-Type", "application/json")
      connection.setRequestProperty("X-Dan-Otp-Device-Token", deviceToken)
      connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
      val code = connection.responseCode
      connection.disconnect()
      when {
        code in 200..299 -> ForwardResult.SUCCESS
        code == 401 -> ForwardResult.AUTH_FAILED
        else -> ForwardResult.RETRY
      }
    } catch (_: Exception) {
      ForwardResult.RETRY
    }
  }

  /**
   * Tell the user when a code was dropped. Silence is the worst failure mode:
   * an OTP that never arrives looks identical to "the setting is off", and the
   * code cannot be re-fetched, so the user needs to know immediately that they
   * must read it off the phone themselves.
   */
  fun notifyFailure(context: Context, authFailed: Boolean) {
    try {
      val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        val channel = NotificationChannel(
          CHANNEL_ID,
          "SMS転送",
          NotificationManager.IMPORTANCE_HIGH,
        )
        manager.createNotificationChannel(channel)
      }
      val text = if (authFailed) {
        "端末の登録が失効しています。アプリでSMS転送をオフ→オンにし直してください。"
      } else {
        "認証コードをサーバーへ送れませんでした。コードは手動で伝えてください。"
      }
      val notification = NotificationCompat.Builder(context, CHANNEL_ID)
        .setSmallIcon(android.R.drawable.stat_notify_error)
        .setContentTitle("認証コードを転送できませんでした")
        .setContentText(text)
        .setStyle(NotificationCompat.BigTextStyle().bigText(text))
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setAutoCancel(true)
        .build()
      NotificationManagerCompat.from(context).notify(CHANNEL_ID.hashCode(), notification)
    } catch (_: Exception) {
      // 通知は補助。失敗しても転送処理そのものは妨げない
    }
  }
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
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import androidx.work.workDataOf
import java.util.concurrent.TimeUnit

class DanSmsForwarderReceiver : BroadcastReceiver() {
  companion object {
    const val PREFS = "danSmsForwarder"
    // The whole broadcast (including goAsync work) must finish inside the
    // system's ~10s limit or the app is killed, so the immediate attempt runs
    // on a much tighter budget than the WorkManager fallback.
    const val FAST_CONNECT_MS = 3000
    const val FAST_READ_MS = 4000
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
    // Forward numeric codes AND one-time links (Instagram password reset,
    // magic sign-in links). The server decides which links are auth links.
    val hasCode = Regex("""\\b\\d{4,8}\\b""").containsMatchIn(body)
    val hasLink = Regex("""https?://\\S+""", RegexOption.IGNORE_CASE).containsMatchIn(body)
    if (!hasCode && !hasLink) return

    val messageId = messages.firstOrNull()?.timestampMillis?.toString() ?: ""

    // Send RIGHT NOW, inside the broadcast, instead of only handing the POST to
    // WorkManager. Receiving an SMS puts this app on the system's temporary
    // power allowlist, so a request issued here gets network access even under
    // Doze / battery saver. Merely enqueueing work throws that window away:
    // ordinary WorkManager jobs are deferrable and the system holds them until
    // the device leaves the restricted state — long after a ~10 minute OTP has
    // expired. That is exactly how codes were silently lost on a low battery.
    val pending = goAsync()
    Thread {
      var result = ForwardResult.RETRY
      try {
        result = DanSmsForwarderSender.post(
          apiBaseUrl, deviceToken, sender, body, messageId,
          FAST_CONNECT_MS, FAST_READ_MS,
        )
      } catch (_: Exception) {
        result = ForwardResult.RETRY
      } finally {
        try {
          when (result) {
            ForwardResult.SUCCESS -> {}
            ForwardResult.AUTH_FAILED -> DanSmsForwarderSender.notifyFailure(context, true)
            // Only fall back to the deferrable queue when the immediate attempt
            // failed; it may still succeed once the device wakes up.
            ForwardResult.RETRY -> enqueueFallback(
              context, apiBaseUrl, deviceToken, sender, body, messageId
            )
          }
        } catch (_: Exception) {
        }
        pending.finish()
      }
    }.start()
  }

  private fun enqueueFallback(
    context: Context,
    apiBaseUrl: String,
    deviceToken: String,
    sender: String,
    body: String,
    messageId: String,
  ) {
    val request = OneTimeWorkRequestBuilder<DanSmsForwardWorker>()
      .setConstraints(
        Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
      )
      .setBackoffCriteria(BackoffPolicy.LINEAR, 30, TimeUnit.SECONDS)
      // Expedited work is less likely to be held back by Doze / battery saver.
      // It is not an exemption, so it stays a fallback rather than the primary
      // path, and it must degrade gracefully when the app is out of quota.
      .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
      .setInputData(
        workDataOf(
          "apiBaseUrl" to apiBaseUrl,
          "deviceToken" to deviceToken,
          "sender" to sender,
          "body" to body,
          "messageId" to messageId,
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

class DanSmsForwardWorker(context: Context, params: WorkerParameters) :
  Worker(context, params) {
  companion object {
    // OTPs expire in ~10 minutes; with linear 30s backoff, attempt 6 lands past
    // that window, so further retries would only deliver dead codes.
    const val MAX_ATTEMPTS = 6
    const val CONNECT_MS = 10000
    const val READ_MS = 15000
  }

  override fun doWork(): Result {
    val apiBaseUrl = inputData.getString("apiBaseUrl") ?: return Result.failure()
    val deviceToken = inputData.getString("deviceToken") ?: return Result.failure()
    if (runAttemptCount >= MAX_ATTEMPTS) {
      // Give up loudly. The code is gone and cannot be re-fetched, so the user
      // has to know to read it off the phone instead of waiting forever.
      DanSmsForwarderSender.notifyFailure(applicationContext, false)
      return Result.failure()
    }

    val result = DanSmsForwarderSender.post(
      apiBaseUrl,
      deviceToken,
      inputData.getString("sender") ?: "",
      inputData.getString("body") ?: "",
      inputData.getString("messageId") ?: "",
      CONNECT_MS,
      READ_MS,
    )
    return when (result) {
      ForwardResult.SUCCESS -> Result.success()
      ForwardResult.AUTH_FAILED -> {
        // Token revoked — retrying cannot help; the user must re-register.
        DanSmsForwarderSender.notifyFailure(applicationContext, true)
        Result.failure()
      }
      ForwardResult.RETRY -> Result.retry()
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
      // Needed on Android 13+ for the "code could not be forwarded" warning.
      'android.permission.POST_NOTIFICATIONS',
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
