package app.done.dan.voice;

import android.content.Context;
import android.content.SharedPreferences;
import io.github.jaredmdobson.concentus.OpusDecoder;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;

/**
 * The pin's always-on recording (2026-10-09): the parts of the day where someone speaks are kept and written down on
 * the home PC (app/services/lifelog.py, scripts/lifelog_worker.py), so Dan can be asked 「今日話してたあれ」「今の聞いてた？」.
 *
 * The pin's own Opus frames are kept as they are (no re-encoding, ~14 MB per hour of speech). Each frame is decoded only
 * to measure loudness: speech is louder than a slowly tracked noise floor. A segment starts with 1 s of what came
 * before, ends after 1.5 s of quiet, and is cut at 60 s. Segments are written to files/lifelog/*.dpo (DPO1 format) and
 * uploaded when the phone can reach Dan's server; nothing is lost while it cannot. All work on this class's threads.
 */
public final class DanPinLifelog {
  private static final int FRAME_MS = 10, PRE_FRAMES = 100, END_QUIET = 150, MAX_FRAMES = 6000, START_NEED = 20;
  private static volatile DanPinLifelog instance;

  private final Context context;
  private final File dir;
  private final BlockingQueue<byte[]> packets = new ArrayBlockingQueue<>(256);
  private final OpusDecoder decoder;
  private final short[] pcm = new short[960];
  private final ArrayDeque<byte[]> pre = new ArrayDeque<>();
  private final ArrayDeque<Boolean> recent = new ArrayDeque<>();
  private int recentSpeech;
  private ByteArrayOutputStream segment;
  private long segmentStart;
  private int segmentFrames, quiet;
  private double floor = 200;
  private volatile boolean closed;

  private DanPinLifelog(Context context) throws Exception {
    this.context = context.getApplicationContext();
    dir = new File(this.context.getExternalFilesDir(null), "lifelog");
    dir.mkdirs();
    decoder = new OpusDecoder(16000, 1);
    Thread t = new Thread(this::run, "DanPinLifelog"); t.setDaemon(true); t.start();
    Thread u = new Thread(this::uploadLoop, "DanPinLifelogUpload"); u.setDaemon(true); u.start();
  }

  public static synchronized DanPinLifelog get(Context context) {
    if (instance == null) {
      try { instance = new DanPinLifelog(context); android.util.Log.i("DanPinBle", "lifelog ready"); }
      catch (Exception e) { android.util.Log.w("DanPinBle", "lifelog unavailable: " + e); }
    }
    return instance;
  }

  private SharedPreferences prefs() { return context.getSharedPreferences("dan_pin", Context.MODE_PRIVATE); }

  /** The signed-in session's token for uploads (the screen hands it over whenever it has a fresh one). */
  public static void setToken(Context context, String token) {
    context.getSharedPreferences("dan_pin", Context.MODE_PRIVATE).edit().putString("token", token).apply();
  }

  /** Bluetooth thread: the raw packet ([index lo, index hi, sub] + one Opus frame). Never blocks. */
  public void offer(byte[] packet) { if (!closed && packet != null && packet.length > 3) packets.offer(packet); }

  private void run() {
    try {
      while (!closed) {
        byte[] p = packets.take();
        byte[] frame = Arrays.copyOfRange(p, 3, p.length);
        double rms = 0;
        try {
          int n = decoder.decode(frame, 0, frame.length, pcm, 0, pcm.length, false);
          long sum = 0;
          for (int i = 0; i < n; i++) sum += (long) pcm[i] * pcm[i];
          rms = n > 0 ? Math.sqrt(sum / (double) n) : 0;
        } catch (Exception e) { continue; }
        // the floor follows quiet quickly and noise slowly, so a long talk does not become the new "quiet"
        floor = rms < floor ? floor * 0.9 + rms * 0.1 : floor * 0.9995 + rms * 0.0005;
        boolean speech = rms > Math.max(floor * 3.0, 300);
        recent.addLast(speech); if (speech) recentSpeech++;
        if (recent.size() > 30 && recent.removeFirst()) recentSpeech--;
        if (segment == null) {
          pre.addLast(frame); if (pre.size() > PRE_FRAMES) pre.removeFirst();
          if (recentSpeech >= START_NEED) open();
        } else {
          append(frame);
          quiet = speech ? 0 : quiet + 1;
          if (quiet >= END_QUIET || segmentFrames >= MAX_FRAMES) close();
        }
      }
    } catch (InterruptedException ignored) {
    } catch (Exception e) {
      android.util.Log.w("DanPinBle", "lifelog stopped: " + e);
    }
  }

  private void open() {
    segment = new ByteArrayOutputStream();
    segmentFrames = 0; quiet = 0;
    segmentStart = System.currentTimeMillis() - (long) pre.size() * FRAME_MS;
    ByteBuffer h = ByteBuffer.allocate(14).order(ByteOrder.LITTLE_ENDIAN);
    h.put(new byte[]{'D', 'P', 'O', '1'}).putLong(segmentStart).putShort((short) FRAME_MS);
    segment.write(h.array(), 0, 14);
    for (byte[] f : pre) append(f);
    pre.clear();
  }

  private void append(byte[] frame) {
    segment.write(frame.length & 255); segment.write((frame.length >> 8) & 255);
    segment.write(frame, 0, frame.length);
    segmentFrames++;
  }

  private void close() {
    byte[] data = segment.toByteArray();
    segment = null;
    if (segmentFrames < 80) return;   // under 0.8 s: a knock or a cough
    File f = new File(dir, segmentStart + ".dpo");
    try (FileOutputStream out = new FileOutputStream(f)) { out.write(data); }
    catch (Exception e) { android.util.Log.w("DanPinBle", "lifelog save failed: " + e); return; }
    android.util.Log.i("DanPinBle", "lifelog segment " + (segmentFrames * FRAME_MS / 1000.0) + " s");
  }

  /** Sends saved segments, oldest first; keeps them on any failure and tries again later. */
  private void uploadLoop() {
    while (!closed) {
      try {
        File[] files = dir.listFiles((d, name) -> name.endsWith(".dpo"));
        String base = prefs().getString("api", null), token = prefs().getString("token", null);
        if (files != null && files.length > 0 && base != null && token != null) {
          Arrays.sort(files);
          for (File f : files) {
            int code = post(base + "/api/v1/lifelog/segment", token, f);
            if (code == 200 || code == 422) { f.delete(); continue; }   // 422: unreadable, never retried
            if (code == 401) android.util.Log.i("DanPinBle", "lifelog upload waits for a fresh sign-in");
            break;
          }
        }
        Thread.sleep(15_000);
      } catch (InterruptedException e) { return; }
      catch (Exception e) { try { Thread.sleep(30_000); } catch (InterruptedException x) { return; } }
    }
  }

  private static int post(String url, String token, File f) {
    HttpURLConnection c = null;
    try {
      byte[] body = new byte[(int) f.length()];
      try (InputStream in = new java.io.FileInputStream(f)) { int at = 0, n; while (at < body.length && (n = in.read(body, at, body.length - at)) > 0) at += n; }
      c = (HttpURLConnection) new URL(url).openConnection();
      c.setConnectTimeout(15_000); c.setReadTimeout(30_000); c.setDoOutput(true); c.setRequestMethod("POST");
      c.setRequestProperty("Authorization", "Bearer " + token);
      c.setRequestProperty("Content-Type", "application/octet-stream");
      c.setFixedLengthStreamingMode(body.length);
      try (OutputStream out = c.getOutputStream()) { out.write(body); }
      return c.getResponseCode();
    } catch (Exception e) {
      return -1;
    } finally { if (c != null) c.disconnect(); }
  }
}
