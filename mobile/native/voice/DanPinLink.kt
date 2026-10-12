package app.done.dan.voice

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.modules.core.DeviceEventManagerModule

/**
 * The one standing BLE link to the Dan pin (2026-10-05). The pin accepts a single connection, so calls, self-tests
 * and the touch input all share this link instead of each connecting on its own. A tap on the pin (control notify
 * 0x10) or 「ヘイダン」 ends the current call, or starts one with the command-center Dan.
 *
 * Runs without the app's screen (2026-10-06): Android starts it when the associated pin appears
 * (DanPinPresenceService), even with the app killed. Once the pin's address is known it connects straight to it,
 * and while the pin is off or away it leaves a passive connect pending, so the link is back the moment the pin
 * powers on. When the app's screen is not running, a tap or 「ヘイダン」 opens it to start the call
 * (a companion app may start its screen from the background).
 */
object DanPinLink {
  private val main = Handler(Looper.getMainLooper())
  private var context: Context? = null
  @Volatile private var react: ReactApplicationContext? = null
  /** The app's screen listens for DanPinTap (App.tsx); without it a call is started by opening the screen. */
  @Volatile var screenListening = false
  /** A tap that arrived while the screen was not running: taken by the screen once it is up. */
  @Volatile var pendingTap = false
  private var pin: DanPinBle? = null
  private var ready = false
  private var wanted = false
  private var retryMs = 3_000L
  private var fastFailures = 0
  private val waiting = mutableListOf<(DanPinBle?) -> Unit>()
  private val closedListeners = mutableListOf<() -> Unit>()
  private var wake: DanPinWake? = null

  private fun prefs(ctx: Context) = ctx.getSharedPreferences("dan_pin", Context.MODE_PRIVATE)
  fun remember(ctx: Context, address: String) { prefs(ctx).edit().putString("address", address.uppercase()).apply() }
  private fun knownAddress(ctx: Context) = prefs(ctx).getString("address", null)

  fun attachReact(ctx: ReactApplicationContext) { react = ctx }
  fun rememberApi(ctx: Context, base: String) { prefs(ctx).edit().putString("api", base).apply() }

  /**
   * Wakes the phone's network toward Dan's server the instant a call is asked for, while the screen and JS are still
   * starting: after the app sat in the background the first request took 11 s (2026-10-06). Logs how long it took.
   */
  private fun warmNetwork(ctx: Context) {
    val base = prefs(ctx).getString("api", null) ?: return
    Thread {
      val began = android.os.SystemClock.elapsedRealtime()
      try {
        val c = java.net.URL("$base/api/v1/chat/me").openConnection() as java.net.HttpURLConnection
        c.connectTimeout = 15_000; c.readTimeout = 15_000
        val code = c.responseCode
        c.disconnect()
        android.util.Log.i("DanPinBle", "network warm: $code in ${android.os.SystemClock.elapsedRealtime() - began} ms")
      } catch (e: Exception) {
        android.util.Log.i("DanPinBle", "network warm failed after ${android.os.SystemClock.elapsedRealtime() - began} ms: $e")
      }
    }.start()
  }

  /** Starts (or keeps) the standing link. Any thread. */
  fun start(ctx: Context) {
    main.post {
      if (ctx is ReactApplicationContext) react = ctx
      if (context == null) context = ctx.applicationContext
      if (wanted) { if (pin == null) { main.removeCallbacksAndMessages(RETRY); connect() }; return@post }
      wanted = true
      connect()
    }
  }

  fun stop() {
    wanted = false
    main.removeCallbacksAndMessages(null)
    pin?.close("link_stopped")
  }

  /** The connected pin, or null. */
  fun current(): DanPinBle? = if (ready) pin else null

  /** Calls back with the pin once connected (immediately if it already is), or null after [timeoutMs]. */
  fun acquire(ctx: Context, timeoutMs: Long, callback: (DanPinBle?) -> Unit) {
    main.post {
      current()?.let { callback(it); return@post }
      waiting += callback
      if (context == null) context = ctx.applicationContext
      if (ctx is ReactApplicationContext) react = ctx
      if (!wanted) { wanted = true; connect() }
      main.postDelayed({ if (waiting.remove(callback)) callback(null) }, timeoutMs)
    }
  }

  /** Notified once when the current link drops (a call falls back to the phone microphone). */
  fun onClosed(listener: () -> Unit) { main.post { closedListeners += listener } }
  fun removeOnClosed(listener: () -> Unit) { main.post { closedListeners -= listener } }

  private val RETRY = Any()

  private fun connect() {
    val ctx = context ?: return
    if (pin != null) return
    lateinit var candidate: DanPinBle
    candidate = DanPinBle(ctx, DanWebRtcAudio.endpoint, object : DanPinBle.Listener {
      override fun ready() {
        main.post {
          if (pin !== candidate) return@post
          ready = true
          retryMs = 3_000L
          fastFailures = 0
          candidate.address()?.let { remember(ctx, it) }
          android.util.Log.i("DanPinBle", "link ready")
          DanPhoneLifelog.pinChanged(true)   // the phone's own recording yields to the pin
          if (wake == null) wake = DanPinWake.create(ctx) { main.post { if (pin != null) wakeWord() } }
          // every microphone packet: 「ヘイダン」 and the always-on recording (DanPinLifelog)
          val w = wake
          val life = DanPinLifelog.get(ctx)
          candidate.rawAudio = java.util.function.Consumer { w?.offer(it); life?.offer(it) }
          waiting.toList().forEach { it(candidate) }
          waiting.clear()
        }
      }
      override fun control(event: Int) {
        main.post { if (pin === candidate && event == 0x10) tap() }
      }
      override fun closed(reason: String) {
        main.post {
          if (pin !== candidate) return@post
          val wasReady = ready
          pin = null
          ready = false
          closedListeners.toList().forEach { it() }
          closedListeners.clear()
          if (wasReady) DanPhoneLifelog.pinChanged(false)
          if (!wasReady) fastFailures++
          android.util.Log.i("DanPinBle", "link closed $reason")
          if (!wanted) return@post
          // Bluetooth switched off: nothing to connect to until it is back; retrying every 0.5 s only spent the battery
          if (reason == "bluetooth_off") main.postAtTime({ connect() }, RETRY, android.os.SystemClock.uptimeMillis() + 10_000)
          else if (knownAddress(ctx) != null) main.postAtTime({ connect() }, RETRY, android.os.SystemClock.uptimeMillis() + 500)
          else {
            main.postAtTime({ connect() }, RETRY, android.os.SystemClock.uptimeMillis() + retryMs)
            retryMs = minOf(retryMs * 2, 60_000L) // unknown pin: scanning costs battery, back off
          }
        }
      }
    })
    pin = candidate
    try {
      val address = knownAddress(ctx)
      // First a fast direct connect (the pin is usually right here); after a miss, Android's passive connect.
      if (address != null) candidate.startDirect(address, fastFailures > 0) else candidate.start()
    } catch (e: Exception) {
      android.util.Log.w("DanPinBle", "link start failed: $e")
      pin = null
      if (wanted) main.postAtTime({ connect() }, RETRY, android.os.SystemClock.uptimeMillis() + retryMs)
    }
  }

  /** 「ヘイダン」: start a conversation; during a call it is ignored (Dan is already listening). */
  private fun wakeWord() {
    if (DanWebRtcAudio.hasPeerOwner()) return
    android.util.Log.i("DanPinBle", "wake -> DanPinTap")
    startCall()
  }

  /** Developer test over adb (PIN_SELFTEST --ez tap true): exactly what a tap on the pin does. */
  fun simulateTap() { main.post { tap() } }

  /** One tap: end the call in progress, otherwise start a conversation with the command-center Dan (JS decides). */
  private fun tap() {
    if (DanWebRtcAudio.hasPeerOwner()) {
      android.util.Log.i("DanPinBle", "tap -> DanVoiceEnd")
      emit("DanVoiceEnd")
      return
    }
    android.util.Log.i("DanPinBle", "tap -> DanPinTap")
    startCall()
  }

  @Volatile private var acknowledgedAt = 0L
  /** True once if the start cue was already played on the pin for the call now starting. */
  fun takeAcknowledged(): Boolean {
    val fresh = android.os.SystemClock.elapsedRealtime() - acknowledgedAt < 30_000
    acknowledgedAt = 0L
    return fresh
  }

  private fun startCall() {
    // The start cue at once, from the pin, like 「OK Google」: the call itself takes seconds to connect, and the cue
    // used to wait for it (2026-10-06: 4-5 s of silence after 「ヘイダン」).
    val ctx0 = context
    ctx0?.let { warmNetwork(it) }
    current()?.let { pin -> if (ctx0 != null) try {
      pin.enableSpeaker(true); pin.playCue(DanWebRtcAudio.wav(ctx0, "dan_ready")); pin.detach()
      acknowledgedAt = android.os.SystemClock.elapsedRealtime()
    } catch (e: Exception) { android.util.Log.w("DanPinBle", "start cue failed: $e") } }
    if (screenListening && emit("DanPinTap")) return
    val ctx = context ?: return
    pendingTap = true
    val launch = ctx.packageManager.getLaunchIntentForPackage(ctx.packageName) ?: return
    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
    android.util.Log.i("DanPinBle", "screen not running: opening it for the call")
    try { ctx.startActivity(launch) } catch (e: Exception) { android.util.Log.w("DanPinBle", "open failed: $e") }
  }

  private fun emit(name: String): Boolean {
    val r = react ?: return false
    if (!r.hasActiveReactInstance()) return false
    r.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit(name, null)
    return true
  }
}
