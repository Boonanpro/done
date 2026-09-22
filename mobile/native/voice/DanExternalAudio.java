package app.done.dan.voice;

import android.content.Context;
import android.media.AudioFormat;
import java.nio.ByteBuffer;
import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.LockSupport;
import org.webrtc.AudioTrackSink;
import org.webrtc.audio.JavaAudioDeviceModule;

/** Local Atom PCM endpoint for one phone-owned peer connection. No network I/O in callbacks. */
public final class DanExternalAudio implements JavaAudioDeviceModule.AudioBufferCallback, AudioTrackSink {
  public static final int SAMPLE_RATE = 48000;
  public static final int FRAME_BYTES = 960;
  private final ReentrantLock routeLock = new ReentrantLock();
  private final DanPcmQueue input = new DanPcmQueue(FRAME_BYTES, 6, 80_000_000L);
  private final DanPcmQueue output = new DanPcmQueue(FRAME_BYTES, 6, 80_000_000L);
  private volatile boolean external;
  private volatile boolean muted;
  private volatile long generation;
  private final AtomicLong formatErrors = new AtomicLong();
  private final AtomicLong inputOfferContention = new AtomicLong();
  private final AtomicLong inputCallbackContention = new AtomicLong();
  private final AtomicLong outputReadContention = new AtomicLong();
  private final AtomicLong outputCallbackContention = new AtomicLong();
  // Observe even on phone/headset routes so the real negotiated sink format can
  // be checked before activating an external speaker. No allocation per frame.
  private volatile int receivedBits, receivedRate, receivedChannels, receivedFrames, receivedBytes;
  private final AtomicLong receivedCallbacks = new AtomicLong();
  // Owned by the ADM capture thread. With AudioRecord disabled, SDK 144 invokes
  // onBuffer in an unpaced loop: the external source must supply its 10ms clock.
  private long captureDeadline, captureGeneration = -1;

  private void paceExternalCapture(int bytesRead) {
    if (bytesRead > 0) { captureDeadline = 0; return; } // Hardware read already paced us.
    long now = System.nanoTime();
    if (captureGeneration != generation || captureDeadline == 0 || now > captureDeadline + 10_000_000L) {
      captureGeneration = generation;
      captureDeadline = now;
    }
    captureDeadline += 10_000_000L;
    long remaining;
    // No route/queue lock is held while waiting. Never replay a late catch-up burst.
    while (external && !Thread.currentThread().isInterrupted()
        && (remaining = captureDeadline - System.nanoTime()) > 0) LockSupport.parkNanos(remaining);
  }

  public JavaAudioDeviceModule createDeviceModule(Context context) {
    return JavaAudioDeviceModule.builder(context)
        .setInputSampleRate(SAMPLE_RATE).setUseStereoInput(false)
        // Leave platform effects available for the phone microphone. Atom calls
        // explicitly request software processing on their capture source, since
        // their PCM is injected after Android's microphone effects.
        .setUseHardwareAcousticEchoCanceler(JavaAudioDeviceModule.isBuiltInAcousticEchoCancelerSupported())
        .setUseHardwareNoiseSuppressor(JavaAudioDeviceModule.isBuiltInNoiseSuppressorSupported())
        .setAudioBufferCallback(this).setEnableVolumeLogger(false)
        .createAudioDeviceModule();
  }

  /** Called by the route owner, outside audio threads. An old socket cannot feed a new route. */
  public long setExternal(boolean enabled) {
    routeLock.lock();
    try {
      external = false;
      generation++;
      input.clear(); output.clear();
      external = enabled;
      return generation;
    } finally { routeLock.unlock(); }
  }

  public boolean offerInput(long token, ByteBuffer frame) {
    if (!routeLock.tryLock()) { inputOfferContention.incrementAndGet(); return false; }
    try { return external && !muted && token == generation && input.offer(frame, System.nanoTime()); }
    finally { routeLock.unlock(); }
  }

  public void setMuted(boolean value) {
    routeLock.lock();
    try { muted = value; input.clear(); } finally { routeLock.unlock(); }
  }

  /** Socket writer reads on its own 10ms clock. Missing frames are always silence. */
  public int readOutput(long token, ByteBuffer frame) {
    if (!routeLock.tryLock()) { outputReadContention.incrementAndGet(); silence(frame); return 0; }
    try {
      if (!external || token != generation) { silence(frame); return 0; }
      return output.read(frame, System.nanoTime());
    } finally { routeLock.unlock(); }
  }

  @Override public long onBuffer(ByteBuffer buffer, int format, int channels, int rate,
      int bytesRead, long captureTimeNs) {
    if (!external) { captureDeadline = 0; return captureTimeNs; }
    paceExternalCapture(bytesRead);
    if (!routeLock.tryLock()) { inputCallbackContention.incrementAndGet(); silenceAll(buffer); return 0; }
    try {
      if (!external) return captureTimeNs;
      int position = buffer.position(), limit = buffer.limit();
      buffer.clear();
      if (muted) {
        silence(buffer);
      } else if (format != AudioFormat.ENCODING_PCM_16BIT || channels != 1 || rate != SAMPLE_RATE) {
        formatErrors.incrementAndGet(); silence(buffer);
      } else {
        input.read(buffer, System.nanoTime());
      }
      buffer.limit(limit); buffer.position(position);
      return 0; // Arrival time is not an Atom capture timestamp.
    } finally { routeLock.unlock(); }
  }

  @Override public void onData(ByteBuffer buffer, int bitsPerSample, int sampleRate,
      int channels, int frames, long timestamp) {
    receivedBits = bitsPerSample; receivedRate = sampleRate;
    receivedChannels = channels; receivedFrames = frames; receivedBytes = buffer.remaining();
    receivedCallbacks.incrementAndGet();
    if (!external) return;
    if (!routeLock.tryLock()) { outputCallbackContention.incrementAndGet(); return; }
    try {
      if (!external) return;
      if (bitsPerSample != 16 || sampleRate != SAMPLE_RATE || channels != 1
          || frames * 2 != FRAME_BYTES || buffer.remaining() != FRAME_BYTES) {
        formatErrors.incrementAndGet(); return;
      }
      output.offer(buffer, System.nanoTime());
    } finally { routeLock.unlock(); }
  }

  public long getFormatErrors() { return formatErrors.get(); }
  public boolean isExternal() { return external; }
  /** Last observed format plus lifetime callback count; diagnostics, not routing state. */
  public long[] receivedFormat() {
    return new long[]{receivedBits, receivedRate, receivedChannels, receivedFrames,
        receivedBytes, receivedCallbacks.get()};
  }
  /** Contention at input socket, input callback, output socket and output callback boundaries. */
  public long[] routeContentionStats() {
    return new long[]{inputOfferContention.get(), inputCallbackContention.get(),
        outputReadContention.get(), outputCallbackContention.get()};
  }
  public long[] inputStats() { return input.snapshot(); }
  public long[] outputStats() { return output.snapshot(); }
  private static void silence(ByteBuffer buffer) {
    for (int i = buffer.position(); i < buffer.limit(); i++) buffer.put(i, (byte) 0);
  }
  private static void silenceAll(ByteBuffer buffer) {
    int position = buffer.position(), limit = buffer.limit();
    buffer.clear(); silence(buffer); buffer.limit(limit); buffer.position(position);
  }
}
