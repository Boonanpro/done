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
  }
  private var running = false
  private var relayMode = false
  private var audioLease: String? = null
  private var connectedAt = 0L
  private var audioPaused = false
  private val handler = Handler(Looper.getMainLooper())
  private val tick = object : Runnable {
    override fun run() {
      if (!running) return
      if(relayMode) {
        val active=DanAtomRelay.callActive()
        val paused=DanAtomRelay.audioPaused()
        if(active && connectedAt==0L || !active && connectedAt!=0L || paused!=audioPaused) {
          if(!active) connectedAt=0L else if(connectedAt==0L) connectedAt=System.currentTimeMillis()
          audioPaused=paused
          getSystemService(NotificationManager::class.java).notify(710,notification())
        }
      }
      if (!pinMode || audioLease != null) emit("DanVoiceTick") // idle pin link: no call clock needed
      // Call control needs consecutive microphone observations <=400ms apart.
      // Keep the same cadence with the Activity asleep; JS timers are not its clock.
      handler.postDelayed(this, if (relayMode) 1000 else 200)
    }
  }
  private fun emit(name: String) {
    reactContext?.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)?.emit(name, null)
  }
  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    val incoming = intent?.getStringExtra("audioLease")
    if (pinMode && running) {
      // The standing pin service: a call borrows it and gives it back; the service itself keeps running.
      when {
        intent?.action == null && DanAudioLease.owns(incoming) -> {
          audioLease = incoming; connectedAt = 0L
          getSystemService(NotificationManager::class.java).notify(710, notification())
          return START_NOT_STICKY
        }
        intent?.action == "CLOSE" -> {
          if (audioLease != null && audioLease == incoming) {
            DanAudioLease.release(audioLease); audioLease = null; connectedAt = 0L
            // No DanVoiceStopped here: it would end the headless task that keeps JS running for the next tap.
            getSystemService(NotificationManager::class.java).notify(710, notification())
          }
          return START_NOT_STICKY
        }
        intent?.action == "PIN" -> { foregroundForPin(); return START_NOT_STICKY }
      }
    }
    if (intent?.action == "PIN" && !running) {
      pinMode = true
      val manager = getSystemService(NotificationManager::class.java)
      manager.createNotificationChannel(NotificationChannel("dan_voice_calls", "Danとの通話", NotificationManager.IMPORTANCE_DEFAULT).apply {
        setSound(null, null)
        enableVibration(false)
      })
      foregroundForPin()
      running = true
      startTask(HeadlessJsTaskConfig("DanVoiceCall", Arguments.createMap(), 0, true))
      handler.post(tick)
      return START_STICKY
    }
    if (intent?.action == "CLOSE") {
      if (DanAudioLease.owns(incoming) && (audioLease == null || audioLease == incoming)) {
        audioLease = incoming
        stopSelfResult(startId)
      }
      return START_NOT_STICKY
    }
    if (!running && (intent?.action == null || intent.action == "RELAY")) {
      if (!DanAudioLease.owns(incoming)) { stopSelfResult(startId); return START_NOT_STICKY }
      audioLease = incoming
    } else if (incoming != null && incoming != audioLease) return START_NOT_STICKY
    if(intent?.action=="RESUME_AUDIO") {DanAtomRelay.resumeAudio();return START_NOT_STICKY}
    if (intent?.action == "END_CALL") {
      if(relayMode) {if(DanAtomRelay.callActive())DanAtomRelay.endCall() else {DanAtomRelay.stop();stopSelf()}} else emit("DanVoiceEnd")
      return START_NOT_STICKY
    }
    if(intent?.action=="RELAY" && !running) relayMode=true
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
   * screen asks (startPinLink), which Android allows while it is visible.
   */
  private fun foregroundForPin() {
    if (withMicrophone) return
    if (Build.VERSION.SDK_INT < 30) { startForeground(710, notification()); withMicrophone = true; return }
    try {
      startForeground(710, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
      withMicrophone = true
    } catch (e: Exception) {
      android.util.Log.i("DanPinBle", "pin service without microphone type for now: $e")
      startForeground(710, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
    }
  }
  private fun notification(): Notification {
    val open = PendingIntent.getActivity(this, 710, packageManager.getLaunchIntentForPackage(packageName), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    val end = PendingIntent.getService(this, 711, Intent(this, DanVoiceCallService::class.java).setAction("END_CALL").putExtra("audioLease",audioLease), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    val builder = Notification.Builder(this, "dan_voice_calls")
      .setSmallIcon(android.R.drawable.stat_sys_phone_call)
      .setContentTitle(if(audioPaused) "Danの音声は一時停止中" else if(connectedAt > 0) "Danと通話中" else if(relayMode) "Atomとイヤホンを接続中" else if(pinMode && audioLease == null) "ダンのピンと接続中" else "Danに接続中")
      .setContentText(if(audioPaused) "ほかのアプリが音声を使用しています。アプリで再開できます" else if(relayMode) "イヤホンを接続すると音声を切り替えます" else if(pinMode && audioLease == null) "ピンを1回押すとダンと話せます" else "ほかのアプリや画面オフでも話せます")
      .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
      .setCategory(Notification.CATEGORY_CALL)
      .setWhen(connectedAt).setShowWhen(connectedAt > 0 && !audioPaused).setUsesChronometer(connectedAt > 0 && !audioPaused)
    if (Build.VERSION.SDK_INT >= 31 && connectedAt > 0 && !audioPaused) {
      val person = Person.Builder().setName("Dan").setImportant(true).build()
      builder.addPerson(person).setStyle(Notification.CallStyle.forOngoingCall(person, end))
    } else builder.addAction(android.R.drawable.ic_menu_close_clear_cancel, "通話を終了", end)
    // Public 36.1 extra also works with our base API-36 compile SDK.
    if(audioPaused) builder.addAction(android.R.drawable.ic_media_play,"会話に戻る",PendingIntent.getService(this,712,Intent(this,DanVoiceCallService::class.java).setAction("RESUME_AUDIO"),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
    if (Build.VERSION.SDK_INT >= 36) builder.addExtras(Bundle().apply { putBoolean("android.requestPromotedOngoing", connectedAt > 0 && !audioPaused) })
    return builder.build()
  }
  override fun onTaskRemoved(rootIntent: Intent?) { emit("DanVoiceEnd"); if (!pinMode) stopSelf() }
  override fun onDestroy() {
    pinMode = false
    if(relayMode) DanAtomRelay.stop()
    running = false
    handler.removeCallbacks(tick)
    emit("DanVoiceStopped")
    stopForeground(STOP_FOREGROUND_REMOVE)
    DanAudioLease.release(audioLease)
    super.onDestroy()
  }
}
