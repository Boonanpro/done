package app.done.dan.voice;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;
import android.content.Context;
import io.github.jaredmdobson.concentus.OpusDecoder;
import java.nio.FloatBuffer;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;

/**
 * 「ヘイダン」 on the pin's microphone, recognised on the phone (2026-10-05). openWakeWord pipeline: Google's frozen
 * melspectrogram + speech-embedding models, then our own classifier trained on the home PC for 「ヘイダン」
 * (D:\dan-hw\kws\train_heydan.py: VOICEVOX/Edge voices, Japanese confusables, 2000 h of general audio, the owner's
 * own recordings). Fast (~0.2 s) and offline. Picovoice was the first choice but is business-only now; the small
 * open engines tried caught it in 1-2 of 4 tries.
 *
 * Audio comes from the standing pin link's Opus packets, decoded again at 16 kHz. Every 80 ms (1280 samples):
 * melspectrogram of the last 1760 samples (8 frames, x/10+2) -> embedding of the last 76 frames (96 values) ->
 * classifier over the last 16 embeddings (1.28 s). All on this class's own thread, never on Bluetooth's.
 * Assets: melspectrogram.onnx, embedding_model.onnx, hey_dan.onnx.
 */
public final class DanPinWake {
  public interface Listener { void heard(); }

  private static final int CHUNK = 1280, MEL_IN = 1760, MEL_FRAMES = 76, EMB = 96, EMB_FRAMES = 16;
  private static final float THRESHOLD = 0.9f;
  private static final int CONSECUTIVE = 2;

  private final OrtEnvironment env = OrtEnvironment.getEnvironment();
  private final OrtSession mel, embedding, classifier;
  private final OpusDecoder decoder;
  private final Listener listener;
  private final BlockingQueue<byte[]> packets = new ArrayBlockingQueue<>(64);
  private final short[] decoded = new short[320];
  private final float[] raw = new float[MEL_IN];
  private int newSamples;
  private final ArrayDeque<float[]> melFrames = new ArrayDeque<>();
  private final ArrayDeque<float[]> embeddings = new ArrayDeque<>();
  // The last 4 s heard, kept so every trigger can be saved and checked later (false ones become training data).
  private final short[] history = new short[16000 * 4];
  private int historyAt;
  private int over;                      // consecutive 80 ms steps above the threshold
  private final java.io.File saveDir;
  private volatile boolean closed;
  private long lastHeard;

  private DanPinWake(Context context, Listener listener) throws Exception {
    this.listener = listener;
    saveDir = new java.io.File(context.getExternalFilesDir(null), "wake");
    saveDir.mkdirs();
    OrtSession.SessionOptions options = new OrtSession.SessionOptions();
    options.setIntraOpNumThreads(1);
    mel = env.createSession(asset(context, "melspectrogram.onnx"), options);
    embedding = env.createSession(asset(context, "embedding_model.onnx"), options);
    classifier = env.createSession(asset(context, "hey_dan.onnx"), options);
    decoder = new OpusDecoder(16000, 1);
    for (int i = 0; i < MEL_FRAMES; i++) { float[] f = new float[32]; java.util.Arrays.fill(f, 1f); melFrames.add(f); }
    Thread thread = new Thread(this::run, "DanPinWake");
    thread.setDaemon(true);
    thread.start();
  }

  /** Null when the models are not in the app. */
  public static DanPinWake create(Context context, Listener listener) {
    try {
      DanPinWake wake = new DanPinWake(context.getApplicationContext(), listener);
      android.util.Log.i("DanPinBle", "wake word ready");
      return wake;
    } catch (Exception e) {
      android.util.Log.w("DanPinBle", "wake word unavailable: " + e);
      return null;
    }
  }

  private static byte[] asset(Context context, String name) throws java.io.IOException {
    try (java.io.InputStream in = context.getAssets().open(name)) {
      java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
      byte[] buf = new byte[16384];
      int n;
      while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
      return out.toByteArray();
    }
  }

  /** Bluetooth thread: hand over the raw packet ([index lo, index hi, sub] + Opus frame); never blocks. */
  public void offer(byte[] packet) { if (!closed) packets.offer(packet); }

  public void close() { closed = true; packets.offer(new byte[0]); }

  private void run() {
    try {
      while (!closed) {
        byte[] packet = packets.take();
        if (closed || packet.length < 4) continue;
        int n = decoder.decode(packet, 3, packet.length - 3, decoded, 0, decoded.length, false);
        for (int i = 0; i < n; i++) {
          System.arraycopy(raw, 1, raw, 0, MEL_IN - 1); // small buffer; 16 k shifts per second is nothing
          raw[MEL_IN - 1] = decoded[i];
          history[historyAt] = decoded[i]; historyAt = (historyAt + 1) % history.length;
          if (++newSamples == CHUNK) { newSamples = 0; step(); }
        }
      }
    } catch (Exception e) {
      android.util.Log.w("DanPinBle", "wake word stopped: " + e);
    }
  }

  private void step() throws Exception {
    try (OnnxTensor in = OnnxTensor.createTensor(env, FloatBuffer.wrap(raw.clone()), new long[]{1, MEL_IN});
         OrtSession.Result r = mel.run(Collections.singletonMap(mel.getInputNames().iterator().next(), in))) {
      float[][][][] out = (float[][][][]) r.get(0).getValue(); // [time=1][1][8][32]
      for (float[] frame : out[0][0]) {
        float[] f = new float[32];
        for (int k = 0; k < 32; k++) f[k] = frame[k] / 10f + 2f;
        melFrames.add(f);
        if (melFrames.size() > MEL_FRAMES) melFrames.poll();
      }
    }
    float[] window = new float[MEL_FRAMES * 32];
    int at = 0;
    for (float[] f : melFrames) { System.arraycopy(f, 0, window, at, 32); at += 32; }
    try (OnnxTensor in = OnnxTensor.createTensor(env, FloatBuffer.wrap(window), new long[]{1, MEL_FRAMES, 32, 1});
         OrtSession.Result r = embedding.run(Collections.singletonMap(embedding.getInputNames().iterator().next(), in))) {
      float[][][][] out = (float[][][][]) r.get(0).getValue(); // [1][1][1][96]
      embeddings.add(out[0][0][0].clone());
      if (embeddings.size() > EMB_FRAMES) embeddings.poll();
    }
    if (embeddings.size() < EMB_FRAMES) return;
    float[] features = new float[EMB_FRAMES * EMB];
    at = 0;
    for (float[] e : embeddings) { System.arraycopy(e, 0, features, at, EMB); at += EMB; }
    float score;
    try (OnnxTensor in = OnnxTensor.createTensor(env, FloatBuffer.wrap(features), new long[]{1, EMB_FRAMES, EMB});
         OrtSession.Result r = classifier.run(Collections.singletonMap(classifier.getInputNames().iterator().next(), in))) {
      score = ((float[][]) r.get(0).getValue())[0][0];
    }
    long now = android.os.SystemClock.elapsedRealtime();
    // Several steps in a row: a real 「ヘイダン」 stays high for a while, a stray noise spikes once (2026-10-09: ~7
    // calls in two days that nobody asked for).
    over = score > THRESHOLD ? over + 1 : 0;
    if (over >= CONSECUTIVE && now - lastHeard > 2000) { // one utterance, one trigger
      lastHeard = now;
      android.util.Log.i("DanPinBle", "wake word heard score=" + score);
      save(score);
      listener.heard();
    }
  }

  /** The 4 s up to the trigger as wake/wake_<time>_<score>.wav (16 kHz mono), for checking and retraining. */
  private void save(float score) {
    try {
      short[] pcm = new short[history.length];
      for (int i = 0; i < pcm.length; i++) pcm[i] = history[(historyAt + i) % history.length];
      String name = new java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.US).format(new java.util.Date());
      java.io.File f = new java.io.File(saveDir, "wake_" + name + "_" + Math.round(score * 100) + ".wav");
      java.nio.ByteBuffer b = java.nio.ByteBuffer.allocate(44 + pcm.length * 2).order(java.nio.ByteOrder.LITTLE_ENDIAN);
      b.put("RIFF".getBytes()).putInt(36 + pcm.length * 2).put("WAVEfmt ".getBytes()).putInt(16).putShort((short) 1).putShort((short) 1)
          .putInt(16000).putInt(32000).putShort((short) 2).putShort((short) 16).put("data".getBytes()).putInt(pcm.length * 2);
      for (short v : pcm) b.putShort(v);
      try (java.io.FileOutputStream out = new java.io.FileOutputStream(f)) { out.write(b.array()); }
    } catch (Exception e) {
      android.util.Log.w("DanPinBle", "wake save failed: " + e);
    }
  }
}
