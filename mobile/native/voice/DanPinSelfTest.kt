package app.done.dan.voice

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat

/**
 * Developer hooks over adb (pin speaker self-test, and the phone recording's test input). Logs under DanPinBle.
 *
 * Who may send (2026-10-12): only a sender holding android.permission.DUMP. The hooks can point the recording's
 * uploads at another server, set the sign-in token, feed audio in and drive the pin, so no other app on the phone may
 * reach them. DUMP is a platform permission of level signature|privileged|development: adb's shell (uid 2000) holds
 * it, an ordinary app cannot obtain it by declaring it (only `adb shell pm grant` could hand it out). So a plain
 * `adb shell am broadcast -a app.done.dan.PIN_SELFTEST …` keeps working without root — on the owner's phone too
 * (D:\dan-hw\tools\pin_phone_ctrl.py, pin_phone_selftest.py) — while the OS drops every other app's broadcast before
 * onReceive: the receiver is registered with that permission as its broadcastPermission, and the broadcast queue
 * checks the sender against it on every Android version (BroadcastSkipPolicy, "requires … due to registered receiver").
 */
object DanPinSelfTest {
  private var registered = false
  @Volatile private var running: DanPinBle? = null

  fun register(context: Context) {
    if (registered) return
    registered = true
    val receiver = object : BroadcastReceiver() {
      override fun onReceive(ctx: Context, intent: Intent) {
        if (phoneLifelogHook(ctx.applicationContext, intent)) return
        if (intent.getBooleanExtra("tap", false)) { DanPinLink.simulateTap(); return }
        val record = intent.getIntExtra("record", 0)
        if (record > 0) { record(ctx.applicationContext, record); return }
        val endure = intent.getStringExtra("endure")
        if (endure != null) { endurance(ctx.applicationContext, endure); return }
        val ctrl = intent.getStringExtra("ctrl")
        if (ctrl != null) { control(ctx.applicationContext, ctrl); return }
        val path = intent.getStringExtra("wav") ?: return
        start(ctx.applicationContext, path, intent.getIntExtra("gain", -1))
      }
    }
    val filter = IntentFilter("app.done.dan.PIN_SELFTEST")
    // Exported — the shell is another uid — but only to senders holding DUMP (see above). ContextCompat hands the
    // permission to Context.registerReceiver(receiver, filter, broadcastPermission, scheduler[, flags]) as it is.
    ContextCompat.registerReceiver(context.applicationContext, receiver, filter, Manifest.permission.DUMP, null, ContextCompat.RECEIVER_EXPORTED)
  }

  /**
   * The phone's own recording (DanPhoneLifelog), over adb without the screen (no root needed: adb's shell holds DUMP):
   *   --es lifelog_api <base>     where segments go (a test server instead of Dan's)
   *   --es lifelog_token <jwt>    the sign-in used for uploads
   *   --ez phone_record true      the owner's switch
   *   --ez fake_pin true          as if the pin's link became ready (false: dropped)
   *   --ez fake_call true         as if a call took the audio (DanAudioLease; false: gave it back)
   *   --es phone_wav <path> [--ei speed N]   a 16 kHz mono WAV in place of the microphone
   *   --ez status true            the state, in the log
   */
  @Volatile private var fakeLease: String? = null
  private fun phoneLifelogHook(context: Context, intent: Intent): Boolean {
    var handled = false
    intent.getStringExtra("lifelog_api")?.let { DanPinLink.rememberApi(context, it); android.util.Log.i("DanPinBle", "selftest: lifelog api $it"); handled = true }
    intent.getStringExtra("lifelog_token")?.let { DanPinLifelog.setToken(context, it); android.util.Log.i("DanPinBle", "selftest: lifelog token set"); handled = true }
    if (intent.hasExtra("phone_record")) { DanPhoneLifelog.setEnabled(context, intent.getBooleanExtra("phone_record", false), null); handled = true }
    if (intent.hasExtra("fake_pin")) { DanPhoneLifelog.get(context); DanPhoneLifelog.pinChanged(intent.getBooleanExtra("fake_pin", false)); handled = true }
    if (intent.hasExtra("fake_call")) {
      DanPhoneLifelog.get(context)
      if (intent.getBooleanExtra("fake_call", false)) { if (fakeLease == null) fakeLease = try { DanAudioLease.acquire("phone") } catch (e: Exception) { android.util.Log.w("DanPinBle", "selftest: fake call refused: $e"); null } }
      else { fakeLease?.let { DanAudioLease.release(it) }; fakeLease = null }
      handled = true
    }
    intent.getStringExtra("phone_wav")?.let { DanPhoneLifelog.get(context).inject(it, intent.getIntExtra("speed", 1)); handled = true }
    if (intent.getBooleanExtra("status", false)) {
      android.util.Log.i("DanPinBle", "selftest: phone lifelog state=${DanPhoneLifelog.status()} capturing=${DanPhoneLifelog.capturing()} frames=${DanPhoneLifelog.framesHanded()} pinMode=${DanVoiceCallService.pinMode}")
      handled = true
    }
    return handled
  }

  private fun start(context: Context, path: String, gain: Int) {
    if (running != null || DanWebRtcAudio.hasPeerOwner()) { android.util.Log.w("DanPinBle", "selftest busy"); return }
    val pcm = readWav(path)
    android.util.Log.i("DanPinBle", "selftest start samples=${pcm.size}")
    val main = Handler(Looper.getMainLooper())
    DanPinLink.current()?.let { link -> // the standing link holds the pin's only connection: borrow it
      main.post {
        if (gain >= 0) link.setPinGain(gain)
        link.enableSpeaker(true)
        main.postDelayed({ link.playCue(pcm) }, 300)
        val ms = pcm.size / 48L
        main.postDelayed({ link.requestPinStats() }, ms + 1500)
        main.postDelayed({ link.detach(); android.util.Log.i("DanPinBle", "closed selftest_done (link kept)") }, ms + 3000)
      }
      return
    }
    lateinit var pin: DanPinBle
    pin = DanPinBle(context, DanExternalAudio(), object : DanPinBle.Listener {
      override fun ready() {
        main.post {
          if (gain >= 0) pin.setPinGain(gain)
          pin.enableSpeaker(true)
          main.postDelayed({ pin.playCue(pcm) }, 300)
          val ms = pcm.size / 48L
          main.postDelayed({ pin.requestPinStats() }, ms + 1500)
          main.postDelayed({ pin.close("selftest_done") }, ms + 3000)
        }
      }
      override fun closed(reason: String) { main.post { running = null } }
    })
    running = pin
    try { pin.start() } catch (e: Exception) { android.util.Log.w("DanPinBle", "selftest failed: $e"); running = null }
  }

  /**
   * Battery endurance: stays connected (mic uplink runs the whole time, as in always-on recording), plays the WAV on
   * the pin speaker about 30 % of the time (Dan talking), and logs the battery level every 5 minutes until the pin
   * stops. Log lines: "endurance ..." under DanPinBle.
   */
  private fun endurance(context: Context, path: String) {
    if (running != null || DanWebRtcAudio.hasPeerOwner()) { android.util.Log.w("DanPinBle", "selftest busy"); return }
    val pcm = readWav(path)
    val main = Handler(Looper.getMainLooper())
    val started = android.os.SystemClock.elapsedRealtime()
    fun minutes() = (android.os.SystemClock.elapsedRealtime() - started) / 60000.0
    lateinit var pin: DanPinBle
    pin = DanPinBle(context, DanExternalAudio(), object : DanPinBle.Listener {
      override fun ready() {
        main.post {
          android.util.Log.i("DanPinBle", "endurance start")
          pin.enableSpeaker(true)
          val talk = object : Runnable { override fun run() {
            if (running !== pin) return
            pin.playCue(pcm)
            main.postDelayed(this, pcm.size / 48L * 100 / 30) // speaking ~30 % of the time
          } }
          val battery = object : Runnable { override fun run() {
            if (running !== pin) return
            android.util.Log.i("DanPinBle", "endurance t=%.1f min".format(minutes()))
            pin.requestBattery()
            main.postDelayed(this, 5 * 60_000L)
          } }
          main.post(talk); main.postDelayed(battery, 2000)
        }
      }
      override fun closed(reason: String) {
        main.post {
          android.util.Log.i("DanPinBle", "endurance end t=%.1f min reason=$reason".format(minutes()))
          running = null
        }
      }
    })
    running = pin
    try { pin.start() } catch (e: Exception) { android.util.Log.w("DanPinBle", "endurance failed: $e"); running = null }
  }

  /**
   * Records the pin's microphone for [seconds] into the app's files dir as pin_record.wav (16 kHz mono), through the
   * standing link — the owner's own 「ヘイダン」 for training the wake word, via the very path it will be heard on.
   */
  private fun record(context: Context, seconds: Int) {
    val link = DanPinLink.current() ?: run { android.util.Log.w("DanPinBle", "record: pin not connected"); return }
    val decoder = io.github.jaredmdobson.concentus.OpusDecoder(16000, 1)
    val pcm = java.io.ByteArrayOutputStream()
    val buf = ShortArray(320)
    val previous = link.rawAudio
    link.rawAudio = java.util.function.Consumer { packet ->
      previous?.accept(packet)
      if (packet.size >= 4) try {
        val n = decoder.decode(packet, 3, packet.size - 3, buf, 0, buf.size, false)
        synchronized(pcm) { for (i in 0 until n) { pcm.write(buf[i].toInt() and 255); pcm.write((buf[i].toInt() shr 8) and 255) } }
      } catch (e: Exception) { }
    }
    android.util.Log.i("DanPinBle", "record start ${seconds}s")
    Handler(Looper.getMainLooper()).postDelayed({
      link.rawAudio = previous
      val data = synchronized(pcm) { pcm.toByteArray() }
      val file = java.io.File(context.getExternalFilesDir(null), "pin_record.wav")
      java.io.FileOutputStream(file).use { out ->
        val h = java.nio.ByteBuffer.allocate(44).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        h.put("RIFF".toByteArray()).putInt(36 + data.size).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
          .putInt(16000).putInt(32000).putShort(2).putShort(16).put("data".toByteArray()).putInt(data.size)
        out.write(h.array()); out.write(data)
      }
      android.util.Log.i("DanPinBle", "record saved ${file.absolutePath} bytes=${data.size}")
    }, seconds * 1000L)
  }

  /** Connects, writes the given hex bytes to the pin's control characteristic, waits, disconnects. */
  private fun control(context: Context, hex: String) {
    if (running != null || DanWebRtcAudio.hasPeerOwner()) { android.util.Log.w("DanPinBle", "selftest busy"); return }
    val bytes = if (hex == "bat") ByteArray(0) else hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    DanPinLink.current()?.let { link ->
      if (hex == "bat") link.requestBattery() else link.writeControl(bytes)
      return
    }
    val main = Handler(Looper.getMainLooper())
    lateinit var pin: DanPinBle
    pin = DanPinBle(context, DanExternalAudio(), object : DanPinBle.Listener {
      override fun ready() {
        main.post {
          if (hex == "bat") pin.requestBattery() else pin.writeControl(bytes)
          main.postDelayed({ pin.close("control_done") }, 4000)
        }
      }
      override fun closed(reason: String) { main.post { running = null } }
    })
    running = pin
    try { pin.start() } catch (e: Exception) { android.util.Log.w("DanPinBle", "control failed: $e"); running = null }
  }

  private fun readWav(path: String): ShortArray {
    val bytes = java.io.File(path).readBytes()
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
}
