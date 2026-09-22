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
  @ReactMethod fun audioEndpointStats(pcId: Int, promise: Promise) { DanWebRtcAudio.stats(pcId, promise) }
  @ReactMethod fun atomCueOnPhone(pcId: Int, promise: Promise) { DanWebRtcAudio.cueOnPhone(pcId, promise) }
  @ReactMethod fun connectAtomAudio(pcId: Int, host: String, key: String, promise: Promise) {
    DanWebRtcAudio.connectAtom(context, pcId, host, key, promise)
  }
  @ReactMethod fun muteExternalAudio(pcId: Int, value: Boolean) { DanWebRtcAudio.mute(pcId, value) }
  private var waitingPlayer: MediaPlayer? = null
  @ReactMethod fun waiting(active: Boolean) {
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
  @ReactMethod fun startAtomRelay(base:String,token:String,host:String,key:String,promise:Promise) {
    // Reject before starting/stopping the shared service. A duplicate request must
    // not enter failure cleanup and tear down the existing conversation.
    if (DanAtomRelay.status().getBoolean("enabled") || DanWebRtcAudio.hasPeerOwner()) {
      promise.reject("VOICE_BUSY", "An audio connection is already active")
      return
    }
    var lease: String? = null
    try {
      lease = DanAudioLease.acquire("relay")
      ContextCompat.startForegroundService(context,Intent(context,DanVoiceCallService::class.java).setAction("RELAY").putExtra("audioLease",lease))
      DanAtomRelay.start(context,base,token,host,key,lease);promise.resolve(true)
    } catch(e:Exception) {
      if (lease != null && DanAudioLease.owns(lease)) {
        DanAtomRelay.stop();context.stopService(Intent(context,DanVoiceCallService::class.java));DanAudioLease.release(lease)
      }
      promise.reject("ATOM_RELAY",e)
    }
  }
  @ReactMethod fun atomRelayStatus(promise:Promise) {promise.resolve(DanAtomRelay.status())}
  @ReactMethod fun resumeAtomAudio() {DanAtomRelay.resumeAudio()}
  @ReactMethod fun endAtomCall() {DanAtomRelay.endCall()}
  @ReactMethod fun muteAtomMicrophone(value:Boolean) {DanAtomRelay.muteMicrophone(value)}
  @ReactMethod fun stopAtomRelay() {
    val lease = DanAudioLease.current("relay") ?: return
    DanAtomRelay.stop()
    context.startService(Intent(context,DanVoiceCallService::class.java).setAction("CLOSE").putExtra("audioLease",lease))
  }
  @ReactMethod fun start(promise: Promise) {
    if (DanAtomRelay.status().getBoolean("enabled")) {
      promise.reject("VOICE_BUSY", "Atom relay is already active")
      return
    }
    var lease: String? = null
    try {
      lease = DanAudioLease.acquire("phone")
      ContextCompat.startForegroundService(context, Intent(context, DanVoiceCallService::class.java).putExtra("audioLease",lease))
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
