package app.done.dan.voice

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper

/** Pin speaker self-test without a voice session (developer use over adb). Logs under DanPinBle. */
object DanPinSelfTest {
  private var registered = false
  @Volatile private var running: DanPinBle? = null

  fun register(context: Context) {
    if (registered) return
    registered = true
    val receiver = object : BroadcastReceiver() {
      override fun onReceive(ctx: Context, intent: Intent) {
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
    if (Build.VERSION.SDK_INT >= 33) context.applicationContext.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
    else context.applicationContext.registerReceiver(receiver, filter)
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
