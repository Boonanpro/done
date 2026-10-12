package app.done.dan.voice;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import io.github.jaredmdobson.concentus.OpusDecoder;
import java.util.ArrayDeque;
import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.locks.LockSupport;

/**
 * One BLE link to the Dan pin (XIAO nRF52840 Sense running the Omi devkit firmware). Its microphone feeds the
 * phone-owned call through the same external PCM endpoint as Atom. Dan's voice goes to the pin's speaker only
 * with the Dan pin firmware (D:/dan-hw, speaker.c), whose speaker characteristic accepts streamed 16 kHz
 * mu-law written without response. The stock Omi one plays a single short clip, so Dan then stays on the phone.
 *
 * Omi audio packets: [index lo, index hi, sub-index] + one 10 ms Opus frame (codec id 20, 16 kHz mono). Without
 * an MTU request no notification ever arrives, so the MTU is raised before subscribing.
 */
@SuppressLint("MissingPermission") // BLUETOOTH_SCAN/CONNECT are requested by the caller before a pin call.
public final class DanPinBle {
  public interface Listener {
    // Both run on Bluetooth threads; enqueue call/route work elsewhere.
    void ready();
    void closed(String reason);
    /** A control event from the pin (0x10 = single tap). */
    default void control(int event) {}
  }
  private static final UUID AUDIO_SERVICE = UUID.fromString("19B10000-E8F2-537E-4F6C-D104768A1214");
  private static final UUID AUDIO_DATA = UUID.fromString("19B10001-E8F2-537E-4F6C-D104768A1214");
  private static final UUID AUDIO_CODEC = UUID.fromString("19B10002-E8F2-537E-4F6C-D104768A1214");
  private static final UUID AUDIO_SPEAKER = UUID.fromString("19B10003-E8F2-537E-4F6C-D104768A1214");
  // Dan pin firmware control service: read = playback counters on the pin (see speaker.c).
  private static final UUID CTRL_SERVICE = UUID.fromString("DA000001-2EA5-4F4D-BB56-874B72CFC984");
  private static final UUID CTRL_CHAR = UUID.fromString("DA000002-2EA5-4F4D-BB56-874B72CFC984");
  private static final UUID BATTERY_SERVICE = UUID.fromString("0000180F-0000-1000-8000-00805f9b34fb");
  private static final UUID BATTERY_LEVEL = UUID.fromString("00002A19-0000-1000-8000-00805f9b34fb");
  private static final byte STREAM_MAGIC_ULAW = (byte) 0xDB;
  private static final int SPEAKER_FRAME = 960; // 20 ms at 48 kHz -> 320 mu-law bytes at 16 kHz per packet
  private static final float[] DECIMATE_TAPS = lowPass();
  private static final float WAITING_GAIN = 0.09f; // same level as the phone's waiting loop
  private static final int SILENCE_PEAK = 64;   // quieter than this is not sent; the pin pads short gaps itself
  private static final UUID CCC = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
  private static final int CODEC_OPUS = 20;
  private static final int FRAME_SAMPLES = 480; // 10 ms at the call's 48 kHz; Opus decodes to it directly.
  private static final long FRAME_NS = 10_000_000L, SCAN_TIMEOUT_MS = 12_000, CONNECT_TIMEOUT_MS = 10_000;
  // BLE delivers frames in bursts of a connection event. Absorb them here and hand the call one frame per 10 ms.
  private static final int PREBUFFER = 4, MAX_QUEUED = 12;

  private final Context context;
  private final DanExternalAudio endpoint;
  private final Listener listener;
  private final Handler main = new Handler(Looper.getMainLooper());
  private final AtomicBoolean started = new AtomicBoolean(), closed = new AtomicBoolean(), announced = new AtomicBoolean();
  private final DanPcmQueue jitter = new DanPcmQueue(FRAME_SAMPLES * 2, 24, 400_000_000L);
  private final short[] pcm = new short[FRAME_SAMPLES];
  private final ByteBuffer frame = ByteBuffer.allocate(FRAME_SAMPLES * 2);
  private volatile long routeToken = -1;
  /** Every raw microphone packet, for listeners such as the wake word (Bluetooth thread; must not block). */
  public volatile java.util.function.Consumer<byte[]> rawAudio;
  private volatile BluetoothGatt gatt;
  private volatile BluetoothLeScanner scanner;
  private volatile Thread feeder, speakerWriter;
  private volatile BluetoothGattCharacteristic speaker;
  private volatile boolean speakerEnabled;
  private final ArrayDeque<byte[]> outgoing = new ArrayDeque<>();
  private boolean writing;
  private final Object cueLock = new Object();
  private short[] cue, waitingLoop;
  private boolean drainCue; // speaker stays on only until the last cue has played
  private int cuePos, waitingPos;
  private long sentPackets, droppedPackets;
  private OpusDecoder decoder;
  private int lastIndex = -1;
  private long packets, concealed;

  public DanPinBle(Context context, DanExternalAudio endpoint, Listener listener) {
    this.context = context.getApplicationContext(); this.endpoint = endpoint; this.listener = listener;
  }

  /** The route owner hands over the endpoint generation once the call uses the pin. */
  public void setRoute(long token) { routeToken = token; }

  /** Whether the pin runs the Dan firmware that can play a stream. Known once audio flows (ready()). */
  public boolean hasSpeaker() { return speaker != null; }

  /** Send Dan's voice (the endpoint's output) to the pin. The route owner mutes the phone speaker first. */
  public void enableSpeaker(boolean enabled) {
    if (enabled) synchronized (cueLock) { cue = null; drainCue = false; } // a new call never inherits an old cue
    speakerEnabled = enabled && speaker != null;
    if (speakerEnabled && speakerWriter == null) startSpeakerWriter();
  }

  public void start() throws Exception {
    if (!started.compareAndSet(false, true)) throw new IllegalStateException("Pin link already started");
    decoder = new OpusDecoder(48000, 1);
    BluetoothManager manager = context.getSystemService(BluetoothManager.class);
    BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
    if (adapter == null || !adapter.isEnabled()) { close("bluetooth_off"); return; }
    scanner = adapter.getBluetoothLeScanner();
    if (scanner == null) { close("bluetooth_off"); return; }
    ScanFilter filter = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(AUDIO_SERVICE)).build();
    ScanSettings settings = new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build();
    scanner.startScan(Collections.singletonList(filter), settings, scan);
    main.postDelayed(() -> { if (gatt == null) close("pin_not_found"); }, SCAN_TIMEOUT_MS);
  }

  /**
   * Connects to a pin already known by address, with no scan. passive = Android's own background connect, which
   * waits as long as needed and connects the moment the pin advertises (pin off or away); otherwise a fast direct
   * connect that gives up after CONNECT_TIMEOUT_MS.
   */
  public void startDirect(String address, boolean passive) throws Exception {
    if (!started.compareAndSet(false, true)) throw new IllegalStateException("Pin link already started");
    decoder = new OpusDecoder(48000, 1);
    BluetoothManager manager = context.getSystemService(BluetoothManager.class);
    BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
    if (adapter == null || !adapter.isEnabled()) { close("bluetooth_off"); return; }
    android.util.Log.i("DanPinBle", (passive ? "waiting for " : "connecting to ") + address);
    gatt = adapter.getRemoteDevice(address).connectGatt(context, passive, callback, BluetoothDevice.TRANSPORT_LE);
    if (!passive) main.postDelayed(() -> { if (!announced.get()) close("pin_connect_timeout"); }, CONNECT_TIMEOUT_MS);
  }

  /** The pin's Bluetooth address once connecting, else null. */
  public String address() { BluetoothGatt g = gatt; return g == null ? null : g.getDevice().getAddress(); }

  private final ScanCallback scan = new ScanCallback() {
    @Override public void onScanResult(int type, ScanResult result) {
      if (closed.get() || gatt != null) return;
      stopScan();
      BluetoothDevice device = result.getDevice();
      android.util.Log.i("DanPinBle", "found " + device.getAddress() + " rssi=" + result.getRssi());
      gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE);
      main.postDelayed(() -> { if (!announced.get()) close("pin_connect_timeout"); }, CONNECT_TIMEOUT_MS);
    }
    @Override public void onScanFailed(int error) { close("scan_failed_" + error); }
  };

  private final BluetoothGattCallback callback = new BluetoothGattCallback() {
    @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
      if (closed.get()) return;
      if (state == BluetoothProfile.STATE_CONNECTED) {
        g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH);
        if (!g.requestMtu(517)) close("mtu_request_failed");
      } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
        close("pin_disconnected_" + status);
      }
    }
    @Override public void onMtuChanged(BluetoothGatt g, int mtu, int status) {
      android.util.Log.i("DanPinBle", "mtu=" + mtu + " status=" + status);
      if (!g.discoverServices()) close("discover_failed");
    }
    @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
      BluetoothGattService service = g.getService(AUDIO_SERVICE);
      BluetoothGattCharacteristic codec = service == null ? null : service.getCharacteristic(AUDIO_CODEC);
      if (codec == null || !g.readCharacteristic(codec)) close("not_a_pin");
    }
    @Override public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value, int status) {
      if (CTRL_CHAR.equals(c.getUuid())) { logPinStats(value); return; }
      if (BATTERY_LEVEL.equals(c.getUuid())) { logBattery(value); return; }
      codecRead(g, value, status);
    }
    @SuppressWarnings("deprecation")
    @Override public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
      if (Build.VERSION.SDK_INT < 33) codecRead(g, c.getValue(), status);
    }
    @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
      if (CTRL_CHAR.equals(d.getCharacteristic().getUuid())) return; // tap notifications are optional
      if (status != BluetoothGatt.GATT_SUCCESS) { close("subscribe_failed_" + status); return; }
      startFeeder();
      subscribeControl(g);
    }
    @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
      synchronized (outgoing) { writing = false; }
      sendNext();
    }
    @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) {
      changed(c, value);
    }
    @SuppressWarnings("deprecation")
    @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
      if (Build.VERSION.SDK_INT < 33) changed(c, c.getValue());
    }
  };

  private void changed(BluetoothGattCharacteristic c, byte[] value) {
    if (CTRL_CHAR.equals(c.getUuid())) {
      if (value != null && value.length > 0) listener.control(value[0] & 255);
      return;
    }
    packet(value);
  }

  /** Subscribes to the pin's control events (touch input). Firmware without them simply has no CCC. */
  @SuppressWarnings("deprecation")
  private void subscribeControl(BluetoothGatt g) {
    BluetoothGattService s = g.getService(CTRL_SERVICE);
    BluetoothGattCharacteristic c = s == null ? null : s.getCharacteristic(CTRL_CHAR);
    BluetoothGattDescriptor ccc = c == null ? null : c.getDescriptor(CCC);
    if (ccc == null || !g.setCharacteristicNotification(c, true)) return;
    if (Build.VERSION.SDK_INT >= 33) g.writeDescriptor(ccc, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
    else { ccc.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE); g.writeDescriptor(ccc); }
  }

  /** Leaves a call but keeps the link: no more microphone into the call, nothing more to the speaker. */
  public void detach() {
    routeToken = -1;
    setWaiting(null);
    // The standby cue is queued just before the call is torn down: let it finish on the pin, then go quiet.
    // (2026-10-05: cutting it off left it queued, and the next call opened with standby, then ready.)
    synchronized (cueLock) {
      if (cue != null) drainCue = true;
      else speakerEnabled = false;
    }
  }

  @SuppressWarnings("deprecation")
  private void codecRead(BluetoothGatt g, byte[] value, int status) {
    if (status != BluetoothGatt.GATT_SUCCESS || value == null || value.length < 1) { close("codec_read_failed"); return; }
    int codec = value[0] & 255;
    if (codec != CODEC_OPUS) { close("codec_" + codec); return; }
    BluetoothGattService service = g.getService(AUDIO_SERVICE);
    BluetoothGattCharacteristic out = service.getCharacteristic(AUDIO_SPEAKER);
    if (out != null && (out.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0) speaker = out;
    android.util.Log.i("DanPinBle", "speaker stream " + (speaker != null ? "available" : "unavailable (stock firmware)"));
    BluetoothGattCharacteristic data = service.getCharacteristic(AUDIO_DATA);
    BluetoothGattDescriptor ccc = data == null ? null : data.getDescriptor(CCC);
    if (ccc == null || !g.setCharacteristicNotification(data, true)) { close("subscribe_failed"); return; }
    boolean written;
    if (Build.VERSION.SDK_INT >= 33) {
      written = g.writeDescriptor(ccc, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) == BluetoothGatt.GATT_SUCCESS;
    } else {
      ccc.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
      written = g.writeDescriptor(ccc);
    }
    if (!written) close("subscribe_failed");
  }

  /** Bluetooth thread. Lost packets (index gaps) are concealed so the call keeps its timing. */
  private void packet(byte[] value) {
    if (closed.get() || value == null || value.length < 4) return;
    java.util.function.Consumer<byte[]> raw = rawAudio;
    if (raw != null) raw.accept(value);
    int index = (value[0] & 255) | ((value[1] & 255) << 8);
    try {
      if (lastIndex >= 0) {
        int missing = (index - lastIndex - 1) & 0xFFFF;
        if (missing > 0 && missing <= 5) for (int i = 0; i < missing; i++) { decode(null, 0); concealed++; }
      }
      lastIndex = index;
      decode(value, value.length - 3);
      packets++;
    } catch (Exception e) {
      android.util.Log.w("DanPinBle", "decode failed: " + e);
      return;
    }
    if (announced.compareAndSet(false, true)) listener.ready();
  }

  private void decode(byte[] packet, int length) throws Exception {
    int samples = packet == null
        ? decoder.decode(null, 0, 0, pcm, 0, FRAME_SAMPLES, false)
        : decoder.decode(packet, 3, length, pcm, 0, FRAME_SAMPLES, false);
    if (samples != FRAME_SAMPLES) return;
    frame.clear();
    for (short s : pcm) { frame.put((byte) s); frame.put((byte) (s >> 8)); }
    frame.flip();
    jitter.offer(frame, System.nanoTime());
  }

  /** Hands the call one frame per 10 ms on its own clock, after a short prebuffer; drifts are trimmed, never replayed. */
  private void startFeeder() {
    Thread thread = new Thread(() -> {
      android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO);
      ByteBuffer out = ByteBuffer.allocateDirect(FRAME_SAMPLES * 2);
      boolean primed = false;
      long deadline = System.nanoTime(), reportAt = deadline;
      while (!closed.get() && !Thread.currentThread().isInterrupted()) {
        deadline += FRAME_NS;
        long remaining;
        while ((remaining = deadline - System.nanoTime()) > 0) LockSupport.parkNanos(remaining);
        long queued = jitter.snapshot()[0];
        if (!primed) { primed = queued >= PREBUFFER; if (!primed) continue; }
        if (queued == 0) { primed = false; continue; }
        while (queued-- > MAX_QUEUED) { out.clear(); jitter.read(out, System.nanoTime()); }
        out.clear();
        if (jitter.read(out, System.nanoTime()) > 0 && routeToken >= 0) endpoint.offerInput(routeToken, out);
        long now = System.nanoTime();
        if (now - reportAt > 15_000_000_000L) {
          long[] q = jitter.snapshot();
          android.util.Log.i("DanPinBle", "packets=" + packets + " concealed=" + concealed + " queued=" + q[0] + " dropped=" + q[1]);
          reportAt = now;
        }
      }
    }, "DanPinFeeder");
    thread.setDaemon(true);
    feeder = thread;
    thread.start();
  }

  /** Asks the pin for its playback counters; they are logged (tag DanPinBle) when they arrive. */
  @SuppressWarnings("deprecation")
  public void requestPinStats() {
    BluetoothGatt g = gatt;
    BluetoothGattService s = g == null ? null : g.getService(CTRL_SERVICE);
    BluetoothGattCharacteristic c = s == null ? null : s.getCharacteristic(CTRL_CHAR);
    synchronized (outgoing) { if (c == null || writing) return; writing = true; }
    if (!g.readCharacteristic(c)) synchronized (outgoing) { writing = false; }
  }

  /** Writes raw bytes to the pin's control characteristic (developer self-test: 0x01 bootloader, 0x03 tone). */
  @SuppressWarnings("deprecation")
  public void writeControl(byte[] value) {
    BluetoothGatt g = gatt;
    BluetoothGattService s = g == null ? null : g.getService(CTRL_SERVICE);
    BluetoothGattCharacteristic c = s == null ? null : s.getCharacteristic(CTRL_CHAR);
    if (c == null) return;
    synchronized (outgoing) { if (writing) return; writing = true; }
    boolean ok;
    if (Build.VERSION.SDK_INT >= 33) {
      ok = g.writeCharacteristic(c, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
    } else {
      c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT); c.setValue(value); ok = g.writeCharacteristic(c);
    }
    if (!ok) synchronized (outgoing) { writing = false; }
    android.util.Log.i("DanPinBle", "control write " + value.length + " bytes " + (ok ? "sent" : "failed"));
  }

  /** Sets the pin's voice output level (percent) over the control service. */
  @SuppressWarnings("deprecation")
  public void setPinGain(int percent) {
    BluetoothGatt g = gatt;
    BluetoothGattService s = g == null ? null : g.getService(CTRL_SERVICE);
    BluetoothGattCharacteristic c = s == null ? null : s.getCharacteristic(CTRL_CHAR);
    if (c == null) return;
    byte[] value = {0x02, (byte) Math.max(0, Math.min(100, percent))};
    synchronized (outgoing) { if (writing) return; writing = true; }
    boolean ok;
    if (Build.VERSION.SDK_INT >= 33) {
      ok = g.writeCharacteristic(c, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
    } else {
      c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT); c.setValue(value); ok = g.writeCharacteristic(c);
    }
    if (!ok) synchronized (outgoing) { writing = false; }
    android.util.Log.i("DanPinBle", "pin gain " + percent + "% " + (ok ? "sent" : "failed"));
  }

  /** Asks the pin for its battery level (standard Battery Service); logged as pin_battery when it arrives. */
  public void requestBattery() {
    BluetoothGatt g = gatt;
    BluetoothGattService s = g == null ? null : g.getService(BATTERY_SERVICE);
    BluetoothGattCharacteristic c = s == null ? null : s.getCharacteristic(BATTERY_LEVEL);
    if (c == null) { android.util.Log.w("DanPinBle", "pin_battery unavailable"); return; }
    synchronized (outgoing) { if (writing) return; writing = true; }
    if (!g.readCharacteristic(c)) synchronized (outgoing) { writing = false; }
  }

  private void logBattery(byte[] v) {
    synchronized (outgoing) { writing = false; }
    if (v != null && v.length >= 1) android.util.Log.i("DanPinBle", "pin_battery " + (v[0] & 255) + "%");
    sendNext();
  }

  private void logPinStats(byte[] v) {
    synchronized (outgoing) { writing = false; }
    if (v != null && v.length >= 24) {
      ByteBuffer b = ByteBuffer.wrap(v).order(java.nio.ByteOrder.LITTLE_ENDIAN);
      android.util.Log.i("DanPinBle", "pin_stats packets=" + b.getInt() + " restarts=" + b.getInt() + " dropped=" + b.getInt()
          + " lost=" + b.getInt() + " uptime_ms=" + b.getInt() + " backlog_ms=" + b.getInt());
    }
    sendNext();
  }

  /** Startup/standby cue (48 kHz mono) played through the pin instead of the phone; replaces any cue in progress. */
  public void playCue(short[] pcm) { synchronized (cueLock) { cue = pcm; cuePos = 0; } }

  /** The "Dan is working" loop (48 kHz mono) through the pin; null stops it. */
  public void setWaiting(short[] loop) { synchronized (cueLock) { waitingLoop = loop; waitingPos = 0; } }

  /** Mixes the cue and the waiting loop into one 48 kHz frame. */
  private void mixCues(short[] pcm) {
    synchronized (cueLock) {
      for (int i = 0; i < pcm.length; i++) {
        int v = pcm[i];
        if (cue != null) {
          v += cue[cuePos++];
          if (cuePos >= cue.length) {
            cue = null;
            if (drainCue) { drainCue = false; speakerEnabled = false; }
          }
        }
        if (waitingLoop != null) {
          v += (int) (waitingLoop[waitingPos++] * WAITING_GAIN);
          if (waitingPos >= waitingLoop.length) waitingPos = 0;
        }
        pcm[i] = (short) Math.max(-32768, Math.min(32767, v));
      }
    }
  }

  /**
   * Reads Dan's voice from the call every 20 ms, mixes in cues, low-passes and decimates 48 -> 16 kHz and sends
   * G.711 mu-law to the pin. Opus decoding on the pin, next to its own always-running Opus encoder for the mic,
   * left too little CPU during calls and the voice broke up (2026-10-04); mu-law is a table lookup there.
   */
  private void startSpeakerWriter() {
    Thread thread = new Thread(() -> {
      android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO);
      ByteBuffer half = ByteBuffer.allocateDirect(FRAME_SAMPLES * 2);
      short[] pcm = new short[SPEAKER_FRAME];
      float[] history = new float[DECIMATE_TAPS.length + SPEAKER_FRAME];
      int seq = 0;
      long deadline = System.nanoTime();
      while (!closed.get() && !Thread.currentThread().isInterrupted()) {
        if (System.nanoTime() - deadline > 5 * FRAME_NS) deadline = System.nanoTime(); // never replay a backlog
        for (int part = 0; part < 2; part++) {
          deadline += FRAME_NS;
          long remaining;
          while ((remaining = deadline - System.nanoTime()) > 0) LockSupport.parkNanos(remaining);
          half.clear();
          long token = routeToken;
          if (!speakerEnabled || token < 0 || endpoint.readOutput(token, half) == 0) {
            for (int i = 0; i < FRAME_SAMPLES; i++) pcm[part * FRAME_SAMPLES + i] = 0;
            continue;
          }
          for (int i = 0; i < FRAME_SAMPLES; i++) {
            pcm[part * FRAME_SAMPLES + i] = (short) ((half.get(i * 2) & 255) | (half.get(i * 2 + 1) << 8));
          }
        }
        if (!speakerEnabled) continue;
        mixCues(pcm);
        int peak = 0;
        for (short v : pcm) peak = Math.max(peak, Math.abs((int) v));
        shaper.process(pcm);
        // Filter history continues across frames so the decimator has no seams.
        int keep = DECIMATE_TAPS.length;
        System.arraycopy(history, SPEAKER_FRAME, history, 0, keep);
        for (int i = 0; i < SPEAKER_FRAME; i++) history[keep + i] = pcm[i];
        if (peak < SILENCE_PEAK) continue;
        byte[] packet = new byte[3 + SPEAKER_FRAME / 3];
        packet[0] = STREAM_MAGIC_ULAW; packet[1] = (byte) seq; packet[2] = (byte) (seq >> 8);
        for (int o = 0; o < SPEAKER_FRAME / 3; o++) {
          int center = keep + o * 3;
          float acc = 0;
          for (int k = 0; k < DECIMATE_TAPS.length; k++) acc += history[center - k] * DECIMATE_TAPS[k];
          packet[3 + o] = linearToUlaw(Math.round(acc));
        }
        seq = (seq + 1) & 0xFFFF;
        synchronized (outgoing) {
          // Live, not late: if the link stalls, the oldest speech goes first.
          while (outgoing.size() >= 8) { outgoing.poll(); droppedPackets++; }
          outgoing.add(packet);
        }
        sendNext();
      }
    }, "DanPinSpeaker");
    thread.setDaemon(true);
    speakerWriter = thread;
    thread.start();
  }

  /**
   * Fits Dan's voice to the pin's 15 x 11 mm speaker (CUI CMS-15118D: 425 Hz - 10 kHz, 0.7 W). Below ~500 Hz it
   * only moves the cone (heard as buzz, and it is what clipped first), so that band is removed; the rest is
   * levelled (slow compressor) and soft-limited, which makes speech louder without driving the speaker past its
   * limit (2026-10-04: "too quiet, slightly distorted").
   */
  private static final class SpeakerShaper {
    private final double[][] hp = { biquadHighPass(500, 0.5412), biquadHighPass(500, 1.3066) };
    private final double[][] z = new double[2][2];
    // Fixed make-up gain, then a look-ahead peak limiter: it lowers the volume just before a peak instead of
    // bending the waveform, so nothing is ever clipped or shaped (the earlier compressor + soft clip distorted).
    static final double MAKEUP = 6.0, CEILING = 0.9; // 6: about +2 dB louder speech than 3 at the same peaks (pin_chain_sim)
    private static final int LOOKAHEAD = 96; // 2 ms at 48 kHz
    private static final double RELEASE = 1 - Math.exp(-1.0 / (0.08 * 48000));
    private final double[] delay = new double[LOOKAHEAD];
    private int at;
    private double gain = 1;

    private static double[] biquadHighPass(double f0, double q) {
      double w = 2 * Math.PI * f0 / 48000, cos = Math.cos(w), alpha = Math.sin(w) / (2 * q), a0 = 1 + alpha;
      return new double[] {(1 + cos) / 2 / a0, -(1 + cos) / a0, (1 + cos) / 2 / a0, -2 * cos / a0, (1 - alpha) / a0};
    }

    void process(short[] pcm) {
      for (int i = 0; i < pcm.length; i++) {
        double x = pcm[i] / 32768.0;
        for (int k = 0; k < 2; k++) { // transposed direct form II
          double[] c = hp[k];
          double y = c[0] * x + z[k][0];
          z[k][0] = c[1] * x - c[3] * y + z[k][1];
          z[k][1] = c[2] * x - c[4] * y;
          x = y;
        }
        delay[at] = x * MAKEUP;
        at = (at + 1) % LOOKAHEAD;
        double peak = 0;
        for (double d : delay) peak = Math.max(peak, Math.abs(d));
        double target = peak > CEILING ? CEILING / peak : 1;
        gain = target < gain ? target : gain + (target - gain) * RELEASE;
        double out = delay[at] * gain; // the oldest sample: the gain was lowered before its peak arrived
        pcm[i] = (short) Math.round(Math.max(-1, Math.min(1, out)) * 32767);
      }
    }
  }
  private final SpeakerShaper shaper = new SpeakerShaper();

  /** 31-tap windowed-sinc low-pass at 7 kHz for 48 -> 16 kHz decimation. */
  private static float[] lowPass() {
    int n = 31;
    float[] h = new float[n];
    double fc = 7000.0 / 48000.0, sum = 0;
    for (int i = 0; i < n; i++) {
      double x = i - (n - 1) / 2.0;
      double sinc = x == 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * x) / (Math.PI * x);
      double window = 0.54 - 0.46 * Math.cos(2 * Math.PI * i / (n - 1));
      h[i] = (float) (sinc * window);
      sum += h[i];
    }
    for (int i = 0; i < n; i++) h[i] /= sum;
    return h;
  }

  /** ITU-T G.711 mu-law. */
  private static byte linearToUlaw(int sample) {
    int sign = 0;
    if (sample < 0) { sign = 0x80; sample = -sample; }
    if (sample > 32635) sample = 32635;
    sample += 0x84;
    int exponent = 7;
    for (int mask = 0x4000; (sample & mask) == 0 && exponent > 0; exponent--, mask >>= 1) { }
    int mantissa = (sample >> (exponent + 3)) & 0x0F;
    return (byte) ~(sign | (exponent << 4) | mantissa);
  }

  /** Android GATT allows one operation in flight; the next packet goes out from onCharacteristicWrite. */
  @SuppressWarnings("deprecation")
  private void sendNext() {
    BluetoothGatt g = gatt;
    BluetoothGattCharacteristic c = speaker;
    if (closed.get() || g == null || c == null) return;
    byte[] packet;
    synchronized (outgoing) {
      if (writing || outgoing.isEmpty()) return;
      packet = outgoing.poll();
      writing = true;
    }
    boolean sent;
    if (Build.VERSION.SDK_INT >= 33) {
      sent = g.writeCharacteristic(c, packet, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE) == 0;
    } else {
      c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
      c.setValue(packet);
      sent = g.writeCharacteristic(c);
    }
    if (sent) sentPackets++;
    else synchronized (outgoing) { writing = false; droppedPackets++; }
  }

  private void stopScan() {
    BluetoothLeScanner s = scanner;
    scanner = null;
    if (s != null) try { s.stopScan(scan); } catch (Exception ignored) {}
  }

  /** Idempotent; the listener hears the first reason only. */
  public void close(String reason) {
    if (!closed.compareAndSet(false, true)) return;
    stopScan();
    main.removeCallbacksAndMessages(null);
    Thread f = feeder;
    if (f != null) f.interrupt();
    Thread w = speakerWriter;
    if (w != null) w.interrupt();
    BluetoothGatt g = gatt;
    if (g != null) { try { g.disconnect(); } catch (Exception ignored) {} try { g.close(); } catch (Exception ignored) {} }
    android.util.Log.i("DanPinBle", "closed " + reason + " packets=" + packets + " concealed=" + concealed
        + " speakerSent=" + sentPackets + " speakerDropped=" + droppedPackets);
    listener.closed(reason);
  }
}
