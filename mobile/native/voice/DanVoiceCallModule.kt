package app.done.dan.voice

import android.content.Intent
import androidx.core.content.ContextCompat
import android.media.AudioAttributes
import android.media.MediaPlayer
import com.facebook.react.bridge.*
import com.facebook.react.ReactPackage
import com.facebook.react.uimanager.ViewManager

class DanVoiceCallModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  @ReactMethod fun bindRemoteAudio(pcId: Int, trackId: String, promise: Promise) {
    DanWebRtcAudio.bind(context, pcId, trackId, promise)
  }
  @ReactMethod fun unbindRemoteAudio(pcId: Int) { DanWebRtcAudio.unbind(pcId) }
  @ReactMethod fun quietSpeechInput(promise: Promise) { DanWebRtcAudio.quietSpeechInput(context, promise) }
  @ReactMethod fun audioEndpointStats(pcId: Int, promise: Promise) { DanWebRtcAudio.stats(pcId, promise) }
  @ReactMethod fun connectPinAudio(pcId: Int, promise: Promise) { DanWebRtcAudio.connectPin(context, pcId, promise) }
  /** Keeps the phone connected to the Dan pin (touch input, 「ヘイダン」, calls), with the screen or without it. */
  @ReactMethod fun startPinLink(apiBase: String?) {
    DanPinLink.attachReact(context)
    if (!apiBase.isNullOrEmpty()) DanPinLink.rememberApi(context, apiBase)
    startStandingLink()
  }
  /** The signed-in session's token, for the always-on recording's uploads (DanPinLifelog). */
  @ReactMethod fun pinToken(token: String?) {
    if (!token.isNullOrEmpty()) DanPinLifelog.setToken(context, token)
  }
  /** 設定「スマホで記録」: until the pin is worn, the phone microphone feeds the always-on recording (DanPhoneLifelog). */
  @ReactMethod fun phoneRecording(enabled: Boolean, apiBase: String?, promise: Promise) {
    try { DanPhoneLifelog.setEnabled(context, enabled, apiBase); promise.resolve(enabled) }
    catch (e: Exception) { promise.reject("PHONE_RECORDING", e) }
  }
  @ReactMethod fun isPhoneRecording(promise: Promise) { promise.resolve(DanPhoneLifelog.isEnabled(context)) }
  /** At sign-in: carry the phone recording on if its switch is on (the service and the microphone type come back). */
  @ReactMethod fun resumePhoneRecording(apiBase: String?) { DanPhoneLifelog.resume(context, apiBase) }
  private fun startStandingLink() {
    UiThreadUtil.runOnUiThread { DanPinPresenceService.startStanding(context) }
  }
  /** The screen's DanPinTap listener is up (true) or gone (false). */
  @ReactMethod fun pinScreen(listening: Boolean) { DanPinLink.screenListening = listening }
  /** A tap or 「ヘイダン」 that opened the screen: true once, then false. */
  @ReactMethod fun takePinTap(promise: Promise) { promise.resolve(DanPinLink.pendingTap); DanPinLink.pendingTap = false }
  /** Registers the pin with Android once (system dialog), so Android brings the link back even with the app killed. */
  @ReactMethod fun associatePin(promise: Promise) {
    if (DanPinPresenceService.associated(context)) { DanPinPresenceService.observe(context); promise.resolve("already"); return }
    val activity = context.currentActivity ?: return promise.resolve("no_screen")
    UiThreadUtil.runOnUiThread {
      DanPinPresenceService.associate(activity) { ok, detail -> if (ok) promise.resolve(detail) else promise.reject("PIN_ASSOCIATE", detail) }
    }
  }
  @ReactMethod fun muteExternalAudio(pcId: Int, value: Boolean) { DanWebRtcAudio.mute(pcId, value) }
  private var waitingPlayer: MediaPlayer? = null
  @ReactMethod fun pinCue(pcId: Int, kind: String, promise: Promise) { DanWebRtcAudio.pinCue(context, pcId, kind, promise) }
  @ReactMethod fun waiting(active: Boolean) {
    // On a pin call the loop plays on the pin. Stopping always clears both, whichever was playing.
    if (DanWebRtcAudio.pinWaiting(context, active) && active) return
    UiThreadUtil.runOnUiThread {
      if (!active) { waitingPlayer?.release(); waitingPlayer = null; return@runOnUiThread }
      if (waitingPlayer != null) return@runOnUiThread
      try {
        val p = MediaPlayer()
        val resource = context.resources.getIdentifier("dan_waiting", "raw", context.packageName)
        p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).build())
        context.resources.openRawResourceFd(resource).use { p.setDataSource(it.fileDescriptor, it.startOffset, it.length) }
        p.isLooping = true; p.setVolume(0.09f, 0.09f)
        p.prepare(); waitingPlayer = p; p.start()
      } catch (e: Exception) { waitingPlayer?.release(); waitingPlayer = null }
    }
  }
  override fun getName() = "DanVoiceCall"
  @ReactMethod fun start(promise: Promise) {
    var lease: String? = null
    try {
      lease = DanAudioLease.acquire("phone")
      val intent = Intent(context, DanVoiceCallService::class.java).putExtra("audioLease",lease)
      if (DanVoiceCallService.pinMode) context.startService(intent) else ContextCompat.startForegroundService(context, intent)
      promise.resolve(lease)
    } catch (e: Exception) { if (lease != null) DanAudioLease.release(lease); promise.reject("VOICE_SERVICE", e) }
  }
  @ReactMethod fun stop(lease: String) {
    if (DanAudioLease.current("phone") != lease) return
    waiting(false)
    context.startService(Intent(context, DanVoiceCallService::class.java).setAction("CLOSE").putExtra("audioLease",lease))
  }
  @ReactMethod fun connected() {
    context.startService(Intent(context, DanVoiceCallService::class.java).setAction("CONNECTED"))
  }
  @ReactMethod fun cue(kind: String, promise: Promise) {
    UiThreadUtil.runOnUiThread {
      var player: MediaPlayer? = null
      try {
        val resource = context.resources.getIdentifier(if (kind == "ready") "dan_ready" else "dan_standby", "raw", context.packageName)
        player = MediaPlayer()
        val active = player!!
        active.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
        context.resources.openRawResourceFd(resource).use { active.setDataSource(it.fileDescriptor, it.startOffset, it.length) }
        active.setVolume(0.75f, 0.75f)
        active.setOnCompletionListener { android.util.Log.i("DanVoiceCue", "$kind completed"); it.release(); promise.resolve(true) }
        active.setOnErrorListener { p, _, _ -> p.release(); promise.resolve(false); true }
        active.prepare(); active.start()
        android.util.Log.i("DanVoiceCue", "$kind started")
      } catch (e: Exception) { player?.release(); promise.reject("VOICE_CUE", e) }
    }
  }
}

class DanVoiceCallPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(DanVoiceCallModule(context))
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}
