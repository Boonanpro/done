package app.done.dan.voice

import android.content.Context
import android.media.AudioManager
import android.media.AudioDeviceInfo
import android.os.Build
import com.oney.WebRTCModule.WebRTCModuleOptions
import com.oney.WebRTCModule.WebRTCModule
import com.oney.WebRTCModule.DanWebRtcAccess
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.Arguments
import org.webrtc.AudioTrack
import org.webrtc.AudioProcessingFactory
import org.webrtc.ExternalAudioProcessingFactory
import org.webrtc.audio.JavaAudioDeviceModule
import com.facebook.react.modules.core.DeviceEventManagerModule

/** Configure the ADM before React Native creates its shared WebRTC peer factory. */
object DanWebRtcAudio {
  val endpoint = DanExternalAudio()
  private val quietSpeech = DanQuietSpeechProcessing()
  private var processingFactory: ExternalAudioProcessingFactory? = null // kept for the peer factory's lifetime
  private var deviceModule: JavaAudioDeviceModule? = null
  // Only access track ownership on the WebRTC executor.
  @Volatile private var ownerPc = -1
  fun hasPeerOwner() = ownerPc >= 0
  private var remote: AudioTrack? = null
  private var atom: DanAtomSocket? = null
  @Volatile private var pin: DanPinBle? = null
  private var cancelAtomConnect: (() -> Unit)? = null
  private var stopRouteObserver: (() -> Unit)? = null
  private var stopQuietSpeechObserver: (() -> Unit)? = null
  private var activeRoute = "phone"
  private fun isHeadset(device: AudioDeviceInfo?) = device?.type in setOf(
    AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET,
    AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_USB_HEADSET)
  // Earbuds whose mic may sit in the ear canal, where a whisper is heard well but quietly.
  private fun isBluetoothHeadset(device: AudioDeviceInfo?) = device?.type in setOf(
    AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET)

  /** Whether a call started now would capture from Bluetooth earbuds; the call then skips noise suppression. */
  fun quietSpeechInput(context: Context, promise: Promise) {
    val audio = context.getSystemService(AudioManager::class.java)
    promise.resolve(Build.VERSION.SDK_INT >= 31 &&
      (isBluetoothHeadset(audio.communicationDevice) || audio.availableCommunicationDevices.any { isBluetoothHeadset(it) }))
  }

  /** Lift quiet speech (after echo cancellation) while the phone-owned call captures from Bluetooth earbuds. WebRTC executor only. */
  private fun observeQuietSpeech(context: Context) {
    stopQuietSpeechObserver?.invoke(); stopQuietSpeechObserver = null
    if (Build.VERSION.SDK_INT < 31) return
    val audio = context.getSystemService(AudioManager::class.java)
    val listener = AudioManager.OnCommunicationDeviceChangedListener { device ->
      quietSpeech.setEnabled(isBluetoothHeadset(device))
    }
    audio.addOnCommunicationDeviceChangedListener({ command -> DanWebRtcAccess.execute { command.run() } }, listener)
    stopQuietSpeechObserver = {
      audio.removeOnCommunicationDeviceChangedListener(listener)
      quietSpeech.setEnabled(false)
    }
    quietSpeech.setEnabled(isBluetoothHeadset(audio.communicationDevice))
  }

  fun cueOnPhone(pcId: Int, promise: Promise) {
    // Queued before teardown, capturing this call's destination, never a later call's.
    DanWebRtcAccess.execute { promise.resolve(ownerPc == pcId && atom != null && activeRoute == "headset") }
  }

  private fun usePhoneAudio() {
    endpoint.setExternal(false)
    deviceModule?.setSpeakerMute(false)
    deviceModule?.setAudioRecordEnabled(true)
    activeRoute = "phone"
  }

  /** Follow the OS-selected communication device, not merely a paired headset.
   * All updates run on the existing WebRTC executor and keep the same peer/track.
   */
  private fun observeAtomRoute(context: Context, pcId: Int, candidate: DanAtomSocket) {
    val audio = context.getSystemService(AudioManager::class.java)
    fun apply(device: AudioDeviceInfo?) {
      if (atom !== candidate || ownerPc != pcId) return
      val headset = isHeadset(device)
      val next = if (headset) "headset" else "atom"
      if (activeRoute == next) return
      candidate.setRemoteCues(headset)
      if (headset) {
        usePhoneAudio()
        candidate.setRoute(-1, true) // Keep Atom control alive, with silent PCM.
        activeRoute = "headset"
      } else {
        val generation = endpoint.setExternal(true)
        deviceModule?.setAudioRecordEnabled(false)
        deviceModule?.setSpeakerMute(true)
        candidate.setRoute(generation, true)
        activeRoute = "atom"
      }
      android.util.Log.i("DanWebRtcAudio", "route_changed route=$next deviceType=${device?.type} peer=$pcId")
    }
    if (Build.VERSION.SDK_INT >= 31) {
      val listener = AudioManager.OnCommunicationDeviceChangedListener { device ->
        try { apply(device) } catch (e: Exception) {
          if (atom === candidate && ownerPc == pcId) candidate.close()
        }
      }
      audio.addOnCommunicationDeviceChangedListener(
        { command -> DanWebRtcAccess.execute { command.run() } }, listener)
      stopRouteObserver = { audio.removeOnCommunicationDeviceChangedListener(listener) }
      apply(audio.communicationDevice)
    } else apply(null)
  }

  fun mute(pcId: Int, value: Boolean) {
    DanWebRtcAccess.execute { if (ownerPc == pcId) endpoint.setMuted(value) }
  }

  /** Attach only to an existing phone-owned call; this never creates a second Live session. */
  fun connectAtom(context: ReactApplicationContext, pcId: Int, host: String, key: String, promise: Promise) {
    DanWebRtcAccess.execute {
      if (ownerPc != pcId || DanAudioLease.current("phone") == null || atom != null) {
        promise.reject("VOICE_ATOM_OWNER", "An existing phone call with no Atom endpoint is required")
        return@execute
      }
      var settled = false
      var requestedOnce = false
      var firstBoot: Int? = null
      lateinit var candidate: DanAtomSocket
      candidate = DanAtomSocket(endpoint, object : DanAtomSocket.Listener {
        override fun intent(requested: Boolean, boot: Int, revision: Int) {
          DanWebRtcAccess.execute {
            if (atom !== candidate || ownerPc != pcId) return@execute
            if (firstBoot != null && firstBoot != boot) { candidate.close(); return@execute }
            firstBoot = boot
            if (!requestedOnce) {
              if (!candidate.supportsRemoteCues()) {
                if (!settled) {
                  settled = true
                  promise.reject("VOICE_ATOM_FIRMWARE", "Atom本体の更新が必要です")
                }
                candidate.close()
                return@execute
              }
              if (!requested) {
                val audio = context.getSystemService(AudioManager::class.java)
                candidate.setRemoteCues(Build.VERSION.SDK_INT >= 31 && isHeadset(audio.communicationDevice))
                if (!candidate.requestWanted(true)) candidate.close()
                return@execute
              }
              requestedOnce = true
              try {
                observeAtomRoute(context, pcId, candidate)
                settled = true
                cancelAtomConnect = null
                promise.resolve(true)
              } catch (e: Exception) {
                candidate.close()
                if (!settled) { settled = true; promise.reject("VOICE_ATOM_ROUTE", e) }
              }
            } else if (!requested) {
              context.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit("DanVoiceEnd", null)
            }
          }
        }
        override fun closed(reason: String) {
          DanWebRtcAccess.execute {
            if (atom !== candidate) return@execute
            atom = null
            stopRouteObserver?.invoke(); stopRouteObserver = null
            cancelAtomConnect = null
            usePhoneAudio()
            if (!settled) { settled = true; promise.reject("VOICE_ATOM_CONNECT", "Local Atom connection failed") }
            else if (requestedOnce && ownerPc == pcId) {
              context.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit("DanVoiceEnd", null)
            }
          }
        }
      })
      atom = candidate
      cancelAtomConnect = {
        if (!settled) { settled = true; promise.reject("VOICE_ATOM_CANCELLED", "Call ended while Atom was connecting") }
      }
      try { candidate.start(host, 48800, key) }
      catch (e: Exception) { atom = null; cancelAtomConnect = null; settled = true; promise.reject("VOICE_ATOM_CONNECT", e) }
    }
  }

  /** Attach the Dan pin to an existing phone-owned call: its microphone, and its speaker when the firmware can stream. */
  fun connectPin(context: ReactApplicationContext, pcId: Int, promise: Promise) {
    DanWebRtcAccess.execute {
      if (ownerPc != pcId || DanAudioLease.current("phone") == null || atom != null || pin != null) {
        promise.reject("VOICE_PIN_OWNER", "An existing phone call with no external device is required")
        return@execute
      }
      // The standing link (DanPinLink) owns the only BLE connection the pin accepts; the call borrows it.
      DanPinLink.acquire(context, 20_000L) { candidate ->
        DanWebRtcAccess.execute {
          if (candidate == null) { promise.reject("VOICE_PIN_CONNECT", "pin_not_found"); return@execute }
          if (ownerPc != pcId || pin != null) { promise.reject("VOICE_PIN_OWNER", "call ended while connecting"); return@execute }
          pin = candidate
          val generation = endpoint.setExternal(true)
          deviceModule?.setAudioRecordEnabled(false)
          // Dan answers from the pin only when its firmware can stream; otherwise from the phone as before.
          val onPin = candidate.hasSpeaker()
          deviceModule?.setSpeakerMute(onPin)
          candidate.setRoute(generation)
          candidate.enableSpeaker(onPin)
          activeRoute = "pin"
          lateinit var lost: () -> Unit
          lost = {
            DanWebRtcAccess.execute {
              if (pin !== candidate) return@execute
              pin = null
              // A pin that drops out mid-call hands the conversation back to the phone microphone.
              if (activeRoute == "pin") usePhoneAudio()
              android.util.Log.w("DanWebRtcAudio", "pin_lost peer=$pcId")
            }
          }
          pinLost = lost
          DanPinLink.onClosed(lost)
          android.util.Log.i("DanWebRtcAudio", "route_changed route=pin speakerOnPin=$onPin peer=$pcId")
          promise.resolve(true)
        }
      }
    }
  }
  private var pinLost: (() -> Unit)? = null

  /** The pin that currently carries Dan's voice, if any: cues and the waiting loop then play there, not on the phone. */
  private fun speakingPin(): DanPinBle? = pin?.takeIf { activeRoute == "pin" && it.hasSpeaker() }

  /** 16-bit mono PCM of a raw WAV resource (the cues are 48 kHz mono). */
  fun wav(context: Context, name: String): ShortArray {
    val id = context.resources.getIdentifier(name, "raw", context.packageName)
    val bytes = context.resources.openRawResource(id).use { it.readBytes() }
    var at = 12
    while (at + 8 <= bytes.size) {
      val size = (bytes[at + 4].toInt() and 255) or ((bytes[at + 5].toInt() and 255) shl 8) or
        ((bytes[at + 6].toInt() and 255) shl 16) or ((bytes[at + 7].toInt() and 255) shl 24)
      if (String(bytes, at, 4, Charsets.US_ASCII) == "data") {
        val n = minOf(size, bytes.size - at - 8) / 2
        return ShortArray(n) { i -> ((bytes[at + 8 + i * 2].toInt() and 255) or (bytes[at + 9 + i * 2].toInt() shl 8)).toShort() }
      }
      at += 8 + size + (size and 1)
    }
    return ShortArray(0)
  }

  /** Plays the ready/standby cue on the pin; resolves false when the phone should play it instead. */
  fun pinCue(context: Context, pcId: Int, kind: String, promise: Promise) {
    DanWebRtcAccess.execute {
      val target = if (ownerPc == pcId) speakingPin() else null
      if (target == null) { promise.resolve(false); return@execute }
      // Already played the moment the pin was tapped or heard 「ヘイダン」 (DanPinLink.startCall): not twice.
      if (kind == "ready" && DanPinLink.takeAcknowledged()) { promise.resolve(true); return@execute }
      val pcm = wav(context, if (kind == "ready") "dan_ready" else "dan_standby")
      target.playCue(pcm)
      // Resolve when it has played (plus the pin's buffering), as the phone cue does.
      android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ promise.resolve(true) }, pcm.size / 48L + 150)
    }
  }

  /** Routes the "working" loop to the pin; false when the phone should play it. */
  fun pinWaiting(context: Context, active: Boolean): Boolean {
    val target = speakingPin() ?: return false
    target.setWaiting(if (active) wav(context, "dan_waiting") else null)
    return true
  }

  fun stats(pcId: Int, promise: Promise) {
    DanWebRtcAccess.execute {
      if (ownerPc != pcId) { promise.resolve(null); return@execute }
      try {
        val fields = arrayOf("queuedFrames", "expiredOrOverflowFrames", "shortReads", "contendedOffers", "contendedReads")
        fun queue(values: LongArray) = Arguments.createMap().apply {
          fields.forEachIndexed { index, name -> putDouble(name, values[index].toDouble()) }
        }
        val contention = endpoint.routeContentionStats()
        promise.resolve(Arguments.createMap().apply {
          putString("counterScope", "process_cumulative")
          putBoolean("external", endpoint.isExternal())
          putString("route", activeRoute)
          putDouble("formatErrors", endpoint.getFormatErrors().toDouble())
          val received = endpoint.receivedFormat()
          putMap("receivedFormat", Arguments.createMap().apply {
            arrayOf("bits", "sampleRate", "channels", "frames", "bytes", "callbacks")
              .forEachIndexed { index, name -> putDouble(name, received[index].toDouble()) }
          })
          putMap("input", queue(endpoint.inputStats()))
          putMap("output", queue(endpoint.outputStats()))
          putMap("routeContention", Arguments.createMap().apply {
            arrayOf("inputSocket", "inputCallback", "outputSocket", "outputCallback")
              .forEachIndexed { index, name -> putDouble(name, contention[index].toDouble()) }
          })
        })
      } catch (e: Exception) { promise.reject("VOICE_AUDIO_STATS", e) }
    }
  }

  fun bind(context: ReactApplicationContext, pcId: Int, trackId: String, promise: Promise) {
    DanWebRtcAccess.execute {
      try {
        require(pcId >= 0) { "Remote peer id required" }
        val rtc = context.getNativeModule(WebRTCModule::class.java)
          ?: error("WebRTC module unavailable")
        val track = rtc.getTrack(pcId, trackId) as? AudioTrack
          ?: error("Remote audio track unavailable")
        if (ownerPc == pcId && remote === track) { promise.resolve(true); return@execute }
        check(ownerPc == -1 || ownerPc == pcId) { "Another call owns audio" }
        remote?.removeSink(endpoint)
        remote = null
        track.addSink(endpoint)
        remote = track
        ownerPc = pcId
        observeQuietSpeech(context)
        val processing = DanWebRtcAccess.processingState(rtc)
        android.util.Log.i("DanWebRtcAudio", "capture_processing aec=${processing.echoCancellation.effective} ns=${processing.noiseSuppression.effective} aecMode=${processing.echoCancellation.requested?.mode} nsMode=${processing.noiseSuppression.requested?.mode}")
        promise.resolve(true)
      } catch (e: Exception) { promise.reject("VOICE_REMOTE_AUDIO", e) }
    }
  }

  fun unbind(pcId: Int) {
    DanWebRtcAccess.execute {
      if (ownerPc != pcId) return@execute
      val previousAtom = atom
      atom = null // An old socket's close callback must not affect the next call.
      stopRouteObserver?.invoke(); stopRouteObserver = null
      stopQuietSpeechObserver?.invoke(); stopQuietSpeechObserver = null
      cancelAtomConnect?.invoke(); cancelAtomConnect = null
      previousAtom?.finish()
      val previousPin = pin
      pin = null
      pinLost?.let { DanPinLink.removeOnClosed(it) }; pinLost = null
      previousPin?.detach() // the call ends, the standing link stays
      usePhoneAudio()
      endpoint.setMuted(false)
      try { remote?.removeSink(endpoint) }
      catch (e: IllegalStateException) {
        android.util.Log.w("DanWebRtcAudio", "Remote track already disposed")
      } finally { remote = null; ownerPc = -1 }
    }
  }

  @Synchronized fun prepare(context: Context) {
    if (deviceModule != null) return
    DanPinSelfTest.register(context) // React modules load lazily; the adb test hook must exist from app start
    val options = WebRTCModuleOptions.getInstance()
    // Learn from late/retransmitted packets too; otherwise recovered Opus can
    // arrive after its playback deadline. This remains adaptive, not a fixed
    // delay on healthy links. Requires per-factory trials in the RN SDK bridge.
    options.fieldTrials = (options.fieldTrials ?: "") +
      "WebRTC-Audio-NetEqDelayManagerConfig/quantile:0.99,use_reorder_optimizer:false,resample_interval_ms:100/" +
      "WebRTC-Audio-NetEqNackTrackerConfig/never_nack_multiple_times:true/"
    check(options.audioDeviceModule == null) { "WebRTC audio module already configured" }
    val module = endpoint.createDeviceModule(context.applicationContext)
    options.audioDeviceModule = module
    // Built when RN WebRTC creates its peer factory: the native library is not loaded yet in Application.onCreate.
    options.audioProcessingFactory = AudioProcessingFactory { environment ->
      ExternalAudioProcessingFactory().also { it.setCapturePostProcessing(quietSpeech); processingFactory = it }.createNative(environment)
    }
    deviceModule = module
    // WebRTCModule takes/releases its native reference when constructing the factory.
    // Keep the Java object for route control; never release the native ADM a second time.
  }
}
