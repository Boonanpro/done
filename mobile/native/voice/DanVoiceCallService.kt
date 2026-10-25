package app.done.dan.voice

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.Bundle
import com.facebook.react.HeadlessJsTaskService
import com.facebook.react.bridge.Arguments
import com.facebook.react.jstasks.HeadlessJsTaskConfig
import com.facebook.react.modules.core.DeviceEventManagerModule

class DanVoiceCallService : HeadlessJsTaskService() {
  companion object {
    /** True while the service runs for the Dan pin. Calls then reuse it instead of starting a new foreground
     *  service, which Android 14+ refuses for the microphone type when the app is not on screen (2026-10-05). */
    @Volatile @JvmStatic var pinMode = false
    @Volatile private var live: DanVoiceCallService? = null
    /** Redraws the standing notification (the phone recording's state is part of it). Any thread. */
    @JvmStatic fun refreshNotification() {
      val s = live ?: return
      s.handler.post { if (s.running) s.getSystemService(NotificationManager::class.java).notify(710, s.notification()) }
    }
  }
  private var running = false
  private var audioLease: String? = null
  private var connectedAt = 0L
  private val handler = Handler(Looper.getMainLooper())
  private val tick = object : Runnable {
    override fun run() {
      if (!running) return
      if (!pinMode || audioLease != null) emit("DanVoiceTick") // idle pin link: no call clock needed
      // Call control needs consecutive microphone observations <=400ms apart.
      // Keep the same cadence with the Activity asleep; JS timers are not its clock.
      handler.postDelayed(this, 200)
    }
  }
  private fun emit(name: String) {
    reactContext?.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)?.emit(name, null)
  }
  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    // Restarted by Android after the process died (START_STICKY, no intent): keep the standing service while the
    // phone recording is wanted. The recording itself resumes below when Android gives the service the microphone
    // type again (the allowance of the original, on-screen start stays with Android's record of the service; seen on
    // API 35); otherwise the notification says it is stopped, and the next time the screen asks (startPinLink / the
    // switch) brings the type and the recording back.
    val restarted = intent == null
    val intent = intent ?: if (!running && DanPhoneLifelog.isEnabled(this)) Intent(this, DanVoiceCallService::class.java).setAction("PIN") else null
    live = this
    val incoming = intent?.getStringExtra("audioLease")
    if (pinMode && running) {
      // The standing pin service: a call borrows it and gives it back; the service itself keeps running — so every
      // answer here is START_STICKY. Android keeps only the LAST onStartCommand's answer (ServiceRecord.stopIfKilled)
      // to decide whether to bring a service back after its process dies; START_NOT_STICKY here (until 2026-10-12)
      // meant that once a PIN had reached the running service (opening the app, the switch) a crash ended the standing
      // service, its notification and the phone recording for good. The service reaches this branch only as the
      // pin's standing service, never for a call alone (those paths below stay START_NOT_STICKY: a call cannot be
      // resumed after a crash), so sticky is the right answer for all three.
      when {
        intent?.action == null && DanAudioLease.owns(incoming) -> {
          audioLease = incoming; connectedAt = 0L
          getSystemService(NotificationManager::class.java).notify(710, notification())
          return START_STICKY
        }
        intent?.action == "CLOSE" -> {
          if (audioLease != null && audioLease == incoming) {
            DanAudioLease.release(audioLease); audioLease = null; connectedAt = 0L
            // No DanVoiceStopped here: it would end the headless task that keeps JS running for the next tap.
            getSystemService(NotificationManager::class.java).notify(710, notification())
          }
          return START_STICKY
        }
        intent?.action == "PIN" -> { foregroundForPin(); return START_STICKY }
      }
    }
    if (intent?.action == "PIN" && !running) {
      pinMode = true
      val manager = getSystemService(NotificationManager::class.java)
      manager.createNotificationChannel(NotificationChannel("dan_voice_calls", "Danとの通話", NotificationManager.IMPORTANCE_DEFAULT).apply {
        setSound(null, null)
        enableVibration(false)
      })
      if (!foregroundForPin()) { pinMode = false; stopSelfResult(startId); return START_NOT_STICKY }
      running = true
      startTask(HeadlessJsTaskConfig("DanVoiceCall", Arguments.createMap(), 0, true))
      handler.post(tick)
      // Brought back after a crash with the microphone type: nothing else would start the recording again (the screen
      // does so only at sign-in). Without the type the microphone would deliver silence, so the recording then waits.
      if (restarted && withMicrophone) DanPhoneLifelog.get(this).refresh("service restarted")
      return START_STICKY
    }
    if (intent?.action == "CLOSE") {
      if (DanAudioLease.owns(incoming) && (audioLease == null || audioLease == incoming)) {
        audioLease = incoming
        stopSelfResult(startId)
      }
      return START_NOT_STICKY
    }
    if (!running && intent?.action == null) {
      if (!DanAudioLease.owns(incoming)) { stopSelfResult(startId); return START_NOT_STICKY }
      audioLease = incoming
    } else if (incoming != null && incoming != audioLease) return START_NOT_STICKY
    if (intent?.action == "END_CALL") {
      emit("DanVoiceEnd")
      return START_NOT_STICKY
    }
    if (intent?.action == "CONNECTED" && running) {
      if (connectedAt == 0L) connectedAt = System.currentTimeMillis()
      getSystemService(NotificationManager::class.java).notify(710, notification())
      return START_NOT_STICKY
    }
    if (running) return START_NOT_STICKY
    val manager = getSystemService(NotificationManager::class.java)
    manager.createNotificationChannel(NotificationChannel("dan_voice_calls", "Danとの通話", NotificationManager.IMPORTANCE_DEFAULT).apply {
      setSound(null, null)
      enableVibration(false)
    })
    val notification = notification()
    if (Build.VERSION.SDK_INT >= 29) startForeground(710, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
    else startForeground(710, notification)
    running = true
    startTask(HeadlessJsTaskConfig("DanVoiceCall", Arguments.createMap(), 0, true))
    handler.post(tick)
    return START_NOT_STICKY
  }
  private var withMicrophone = false
  /**
   * Started by Android when the pin appears (app killed, screen off), the microphone type is refused: the pin's
   * own microphone needs none, so run as a connected device then, and add the microphone type the next time the
   * screen asks (startPinLink / the phone recording's switch), which Android allows while it is visible.
   * The connected-device type needs a Bluetooth permission; without one (the phone recording alone, 2026-10-12) the
   * microphone type by itself is tried, and when Android allows neither the service steps back instead of crashing.
   * Returns false when it could not become a foreground service.
   */
  private fun foregroundForPin(): Boolean {
    if (withMicrophone) return true
    if (Build.VERSION.SDK_INT < 30) { startForeground(710, notification()); withMicrophone = true; return true }
    val attempts = listOf(
      ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
      ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,        // no Bluetooth permission: the phone recording alone
      ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)  // from the background (the companion pin appeared): no microphone yet
    for (type in attempts) {
      try {
        startForeground(710, notification(), type)
        withMicrophone = (type and ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) != 0
        if (!withMicrophone) android.util.Log.i("DanPinBle", "pin service without microphone type for now")
        return true
      } catch (e: Exception) {
        android.util.Log.i("DanPinBle", "pin service type $type refused: ${e.message?.take(140)}")
      }
    }
    android.util.Log.w("DanPinBle", "pin service cannot run in the foreground now")
    return false
  }
  /**
   * The standing notification's words for the phone recording (設定「スマホで記録」): recording; or stopped although the
   * switch is on — after Android brought the service back without the microphone type (the process died; after a phone
   * restart the service does not stand at all, so there is no notification then), when the microphone could not be
   * opened, or when its permission went away — so the owner can see it is not recording and knows what brings it
   * back. Null when the pin or a call has the audio: the pin's own words then.
   */
  private fun phoneRecordingWords(): Pair<String, String>? {
    if (DanPhoneLifelog.capturing()) return "スマホで記録中" to "声のある所だけを記録しています。設定「スマホで記録」で止められます"
    if (!DanPhoneLifelog.isEnabled(this)) return null
    return when (DanPhoneLifelog.status()) {
      "pin", "call", "test_input" -> null
      "no_permission" -> "記録は止まっています" to "マイクの許可が外れています。許可を戻すと再開します"
      else -> "記録は止まっています" to "アプリを開くと再開します"
    }
  }
  private fun notification(): Notification {
    val phone = if (pinMode && audioLease == null) phoneRecordingWords() else null
    val open = PendingIntent.getActivity(this, 710, packageManager.getLaunchIntentForPackage(packageName), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    val end = PendingIntent.getService(this, 711, Intent(this, DanVoiceCallService::class.java).setAction("END_CALL").putExtra("audioLease",audioLease), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    val builder = Notification.Builder(this, "dan_voice_calls")
      .setSmallIcon(android.R.drawable.stat_sys_phone_call)
      .setContentTitle(if(connectedAt > 0) "Danと通話中" else if(phone != null) phone.first else if(pinMode && audioLease == null) "ダンのピンと接続中" else "Danに接続中")
      .setContentText(if(phone != null) phone.second else if(pinMode && audioLease == null) "ピンを1回押すとダンと話せます" else "ほかのアプリや画面オフでも話せます")
      .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
      .setCategory(Notification.CATEGORY_CALL)
      .setWhen(connectedAt).setShowWhen(connectedAt > 0).setUsesChronometer(connectedAt > 0)
    if (Build.VERSION.SDK_INT >= 31 && connectedAt > 0) {
      val person = Person.Builder().setName("Dan").setImportant(true).build()
      builder.addPerson(person).setStyle(Notification.CallStyle.forOngoingCall(person, end))
    } else builder.addAction(android.R.drawable.ic_menu_close_clear_cancel, "通話を終了", end)
    // Public 36.1 extra also works with our base API-36 compile SDK.
    if (Build.VERSION.SDK_INT >= 36) builder.addExtras(Bundle().apply { putBoolean("android.requestPromotedOngoing", connectedAt > 0) })
    return builder.build()
  }
  override fun onTaskRemoved(rootIntent: Intent?) { emit("DanVoiceEnd"); if (!pinMode) stopSelf() }
  override fun onDestroy() {
    pinMode = false
    live = null
    running = false
    handler.removeCallbacks(tick)
    emit("DanVoiceStopped")
    stopForeground(STOP_FOREGROUND_REMOVE)
    DanAudioLease.release(audioLease)
    super.onDestroy()
  }
}
