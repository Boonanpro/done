package app.done.dan.voice

import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.core.app.NotificationCompat

/**
 * After the phone was switched off (the battery ran out, 2026-11-08) or the app was updated, the phone recording
 * (DanPhoneLifelog) stayed stopped until the owner happened to open the app. Android 14+ refuses to start the
 * microphone type of a foreground service from BOOT_COMPLETED, so the receiver cannot simply start recording; it
 * posts 「録音を再開」 instead, and the tap opens [DanLifelogResumeActivity], a see-through screen that starts the
 * recording while it is on screen (which Android allows) and closes itself.
 */
object DanLifelogResume {
  const val NOTIFICATION_ID = 712
  private const val CHANNEL = "dan_lifelog_resume"

  /** The switch is on but nothing records: tell the owner, one tap brings it back. */
  @JvmStatic fun offer(context: Context, why: String) {
    if (!DanPhoneLifelog.isEnabled(context) || DanPhoneLifelog.capturing()) return
    val manager = context.getSystemService(NotificationManager::class.java)
    manager.createNotificationChannel(NotificationChannel(CHANNEL, "常時録音の再開", NotificationManager.IMPORTANCE_HIGH))
    val open = PendingIntent.getActivity(context, NOTIFICATION_ID,
      Intent(context, DanLifelogResumeActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION),
      PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    manager.notify(NOTIFICATION_ID, NotificationCompat.Builder(context, CHANNEL)
      .setSmallIcon(android.R.drawable.ic_btn_speak_now)
      .setContentTitle("常時録音が止まっています")
      .setContentText("押すと録音を再開します")
      .setContentIntent(open)
      .addAction(0, "録音を再開", open)
      .setAutoCancel(true)
      .setCategory(NotificationCompat.CATEGORY_REMINDER)
      .setPriority(NotificationCompat.PRIORITY_HIGH)
      .build())
    android.util.Log.i("DanPinBle", "phone lifelog: resume offered ($why)")
  }

  /** The recording is running again (from the tap, the app or the switch): the offer is moot. */
  @JvmStatic fun withdraw(context: Context) {
    context.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
  }
}

/** Phone switched on / app updated: offer the resume when the switch is on. */
class DanLifelogResumeReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    when (intent.action) {
      Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED -> DanLifelogResume.offer(context, intent.action ?: "")
    }
  }
}

/**
 * The tap on 「録音を再開」. While this screen is shown the app is in the foreground, so the standing service gets the
 * microphone type; the screen stays (see-through) until the microphone is open, at most 3 s, then closes.
 */
class DanLifelogResumeActivity : Activity() {
  private val handler = Handler(Looper.getMainLooper())
  private var started = false
  private var waited = 0

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    DanLifelogResume.withdraw(this)
  }

  override fun onResume() {
    super.onResume()
    if (started) return
    started = true
    DanPhoneLifelog.resume(this, null)
    handler.post(object : Runnable {
      override fun run() {
        if (DanPhoneLifelog.capturing() || waited >= 3000) { finish(); overridePendingTransition(0, 0); return }
        waited += 100
        handler.postDelayed(this, 100)
      }
    })
  }

  override fun onDestroy() { handler.removeCallbacksAndMessages(null); super.onDestroy() }
}
