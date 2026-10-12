package app.done.dan.voice;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import androidx.core.content.ContextCompat;
import io.github.jaredmdobson.concentus.OpusApplication;
import io.github.jaredmdobson.concentus.OpusEncoder;
import io.github.jaredmdobson.concentus.OpusSignal;
import java.io.File;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Until the pin can be worn every day (2026-10-12): the phone's own microphone feeds the same always-on recording
 * (DanPinLifelog) in the pin's own shape — 10 ms Opus frames, 16 kHz mono, wrapped as Omi packets
 * ([index lo, index hi, sub] + frame) — so the speech cutting, the .dpo files, the uploads and the PC side stay as
 * they are. It records only while the owner's switch (設定「スマホで記録」) is on, no pin is linked (the pin takes over
 * the moment its link is ready, DanPinLink) and no call holds the audio (DanAudioLease: phone calls and the Atom
 * relay). It captures inside the standing pin foreground service (DanVoiceCallService PIN, microphone type), so
 * the screen may be off and the phone in a pocket; a partial wake lock keeps the CPU up between frames.
 */
public final class DanPhoneLifelog {
  private static final String TAG = "DanPinBle";
  private static final int RATE = 16000, FRAME = 160;          // 10 ms, the pin's frame length
  private static final int BITRATE = 32_000, COMPLEXITY = 5;   // the pin's bitrate (firmware config.h); complexity for a phone CPU
  private static volatile DanPhoneLifelog instance;

  private final Context context;
  private final Handler main = new Handler(Looper.getMainLooper());
  private final AtomicReference<Thread> worker = new AtomicReference<>();
  private volatile boolean pinReady, callActive, injecting;
  private volatile String state = "off";
  private volatile long frames;   // frames handed over since the app started (diagnostics)
  private int index;              // packet index, counted as the pin counts

  private DanPhoneLifelog(Context ctx) {
    context = ctx.getApplicationContext();
    pinReady = DanPinLink.INSTANCE.current() != null;
    callActive = DanAudioLease.active();
  }

  public static DanPhoneLifelog get(Context ctx) {
    DanPhoneLifelog i = instance;
    if (i == null) synchronized (DanPhoneLifelog.class) { i = instance; if (i == null) instance = i = new DanPhoneLifelog(ctx); }
    return i;
  }

  private static SharedPreferences prefs(Context ctx) { return ctx.getSharedPreferences("dan_pin", Context.MODE_PRIVATE); }

  /** The owner's switch, as saved. */
  public static boolean isEnabled(Context ctx) { return prefs(ctx).getBoolean("phone_record", false); }

  /** The owner's switch. [apiBase] (when given) is where the segments go, as startPinLink remembers it. */
  public static void setEnabled(Context ctx, boolean on, String apiBase) {
    prefs(ctx).edit().putBoolean("phone_record", on).apply();
    if (apiBase != null && !apiBase.isEmpty()) DanPinLink.INSTANCE.rememberApi(ctx, apiBase);
    DanPhoneLifelog self = get(ctx);
    if (on) self.ensureService();
    self.refresh(on ? "switch on" : "switch off");
  }

  /** At app start or sign-in: carry on if the switch is on (the service is brought back; the pin link has its own). */
  public static void resume(Context ctx, String apiBase) {
    if (!isEnabled(ctx)) return;
    if (apiBase != null && !apiBase.isEmpty()) DanPinLink.INSTANCE.rememberApi(ctx, apiBase);
    DanPhoneLifelog self = get(ctx);
    self.ensureService();
    self.refresh("resume");
  }

  /** True while frames are being taken from the phone microphone. */
  public static boolean capturing() { DanPhoneLifelog i = instance; return i != null && i.worker.get() != null; }
  /** off / no_permission / pin / call / test_input / recording — for the notification, logs and the adb hook. */
  public static String status() { DanPhoneLifelog i = instance; return i == null ? "off" : i.state; }
  public static long framesHanded() { DanPhoneLifelog i = instance; return i == null ? 0 : i.frames; }

  /** DanPinLink: the pin's link became ready (true) or dropped (false). Any thread. */
  public static void pinChanged(boolean ready) {
    DanPhoneLifelog i = instance;
    if (i != null) { i.pinReady = ready; i.refresh(ready ? "pin ready" : "pin gone"); }
  }

  /** DanAudioLease: a call (phone or relay) took the audio (true) or gave it back (false). Any thread. */
  public static void leaseChanged(boolean active) {
    DanPhoneLifelog i = instance;
    if (i != null) { i.callActive = active; i.refresh(active ? "call" : "call ended"); }
  }

  /** The standing service (DanVoiceCallService PIN). Started from the screen, Android grants the microphone type. */
  private void ensureService() {
    try {
      Intent intent = new Intent(context, DanVoiceCallService.class).setAction("PIN");
      if (DanVoiceCallService.getPinMode()) context.startService(intent); else ContextCompat.startForegroundService(context, intent);
    } catch (Exception e) { android.util.Log.w(TAG, "phone lifelog: service not started: " + e); }
  }

  /** Decides from the switch, the pin, the calls and the permission; starts or stops the capture. Any thread. */
  public synchronized void refresh(String why) {
    boolean enabled = isEnabled(context);
    boolean permitted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    boolean want = enabled && !pinReady && !callActive && !injecting && permitted;
    String next = !enabled ? "off" : !permitted ? "no_permission" : pinReady ? "pin" : callActive ? "call" : injecting ? "test_input" : "recording";
    if (want && worker.get() == null) start();
    else if (!want) stop();
    if (!next.equals(state)) {
      state = next;
      android.util.Log.i(TAG, "phone lifelog: " + next + " (" + why + ")");
      DanVoiceCallService.refreshNotification();
    }
  }

  private void start() {
    Thread t = new Thread(this::run, "DanPhoneLifelog");
    t.setDaemon(true);
    worker.set(t);
    t.start();
  }

  private void stop() {
    Thread t = worker.getAndSet(null);
    if (t != null) t.interrupt();
  }

  private static OpusEncoder encoder() throws Exception {
    OpusEncoder e = new OpusEncoder(RATE, 1, OpusApplication.OPUS_APPLICATION_VOIP);
    e.setBitrate(BITRATE);
    e.setUseVBR(true);
    e.setUseConstrainedVBR(false);
    e.setComplexity(COMPLEXITY);
    e.setSignalType(OpusSignal.OPUS_SIGNAL_VOICE);
    return e;
  }

  /** One 10 ms frame, encoded and handed over as the pin hands its own. */
  private void hand(OpusEncoder encoder, DanPinLifelog sink, short[] pcm, byte[] out) throws Exception {
    int n = encoder.encode(pcm, 0, FRAME, out, 0, out.length);
    if (n <= 0) return;
    byte[] packet = new byte[3 + n];
    packet[0] = (byte) index; packet[1] = (byte) (index >> 8); packet[2] = 0;
    index = (index + 1) & 0xFFFF;
    System.arraycopy(out, 0, packet, 3, n);
    sink.offer(packet);
    frames++;
  }

  private void run() {
    Thread me = Thread.currentThread();
    AudioRecord record = null;
    PowerManager.WakeLock lock = null;
    long handed = frames;
    try {
      DanPinLifelog sink = DanPinLifelog.get(context);
      if (sink == null) throw new IllegalStateException("lifelog unavailable");
      OpusEncoder encoder = encoder();
      int min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
      // 1 s of buffer: a GC pause or a busy moment must not drop audio
      record = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
          AudioFormat.ENCODING_PCM_16BIT, Math.max(min, RATE * 2));
      if (record.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("microphone not available");
      PowerManager pm = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
      lock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Dan:PhoneLifelog");
      lock.acquire();
      record.startRecording();
      if (record.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IllegalStateException("microphone did not start");
      android.util.Log.i(TAG, "phone lifelog: microphone open");
      short[] pcm = new short[FRAME];
      byte[] out = new byte[1275];
      int at = 0;
      while (worker.get() == me && !me.isInterrupted()) {
        int n = record.read(pcm, at, FRAME - at);
        if (n < 0) throw new IllegalStateException("microphone read " + n);
        at += n;
        if (at < FRAME) continue;
        at = 0;
        hand(encoder, sink, pcm, out);
      }
    } catch (Exception e) {
      android.util.Log.w(TAG, "phone lifelog: stopped: " + e);
      main.postDelayed(() -> refresh("retry"), 30_000);
    } finally {
      if (record != null) { try { record.stop(); } catch (Exception ignored) {} record.release(); }
      if (lock != null && lock.isHeld()) lock.release();
      worker.compareAndSet(me, null);
      android.util.Log.i(TAG, "phone lifelog: microphone closed after " + (frames - handed) + " frames");
    }
  }

  /**
   * Developer test over adb (PIN_SELFTEST --es phone_wav <path> [--ei speed N]): a 16 kHz mono WAV in place of the
   * microphone, through the very same encoder and hand-over, at [speed] × real time (0 = as fast as possible). The
   * microphone pauses meanwhile. Two seconds of silence follow so the last segment closes.
   */
  public void inject(String path, int speed) {
    Thread t = new Thread(() -> {
      injecting = true;
      refresh("test input");
      try {
        short[] all = readWav(new File(path));
        DanPinLifelog sink = DanPinLifelog.get(context);
        if (sink == null) throw new IllegalStateException("lifelog unavailable");
        OpusEncoder encoder = encoder();
        short[] pcm = new short[FRAME];
        byte[] out = new byte[1275];
        long began = System.nanoTime(), next = began;
        int count = all.length / FRAME + 200;
        for (int f = 0; f < count; f++) {
          int i = f * FRAME;
          if (i + FRAME <= all.length) System.arraycopy(all, i, pcm, 0, FRAME); else Arrays.fill(pcm, (short) 0);
          hand(encoder, sink, pcm, out);
          if (speed > 0) {
            next += 10_000_000L / speed;
            long wait = next - System.nanoTime();
            if (wait > 0) Thread.sleep(wait / 1_000_000L, (int) (wait % 1_000_000L));
          }
        }
        android.util.Log.i(TAG, "phone lifelog: test input done frames=" + count + " in " + (System.nanoTime() - began) / 1_000_000 + " ms");
      } catch (Exception e) {
        android.util.Log.w(TAG, "phone lifelog: test input failed: " + e);
      } finally {
        injecting = false;
        refresh("test input done");
      }
    }, "DanPhoneLifelogTest");
    t.setDaemon(true);
    t.start();
  }

  /** 16-bit mono PCM of a plain WAV file (the 16 kHz mono test input). */
  private static short[] readWav(File file) throws Exception {
    byte[] bytes = java.nio.file.Files.readAllBytes(file.toPath());
    int at = 12;
    while (at + 8 <= bytes.length) {
      int size = (bytes[at + 4] & 255) | ((bytes[at + 5] & 255) << 8) | ((bytes[at + 6] & 255) << 16) | ((bytes[at + 7] & 255) << 24);
      if (bytes[at] == 'd' && bytes[at + 1] == 'a' && bytes[at + 2] == 't' && bytes[at + 3] == 'a') {
        int n = Math.min(size, bytes.length - at - 8) / 2;
        short[] pcm = new short[n];
        for (int i = 0; i < n; i++) pcm[i] = (short) ((bytes[at + 8 + i * 2] & 255) | (bytes[at + 9 + i * 2] << 8));
        return pcm;
      }
      at += 8 + size + (size & 1);
    }
    throw new IllegalStateException("no data chunk");
  }
}
