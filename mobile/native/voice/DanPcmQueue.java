package app.done.dan.voice;

import java.nio.ByteBuffer;
import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.atomic.AtomicLong;

/** Bounded PCM frames; neither an audio callback nor a socket thread waits on the other. */
public final class DanPcmQueue {
  private final ReentrantLock lock = new ReentrantLock();
  private final byte[][] frames;
  private final long[] arrivals;
  private final int frameBytes;
  private static final byte[] SILENCE = new byte[960];
  private final long maxAgeNs;
  private int head, size, offset;
  private long dropped, underflow;
  private final AtomicLong contendedOffers = new AtomicLong();
  private final AtomicLong contendedReads = new AtomicLong();

  public DanPcmQueue(int frameBytes, int capacity, long maxAgeNs) {
    if (frameBytes <= 0 || capacity <= 0 || maxAgeNs <= 0) throw new IllegalArgumentException();
    this.frameBytes = frameBytes;
    this.maxAgeNs = maxAgeNs;
    frames = new byte[capacity][frameBytes];
    arrivals = new long[capacity];
  }

  /** Caller retains ownership of src; copy immediately, preserving its position. */
  public boolean offer(ByteBuffer src, long nowNs) {
    if (src.remaining() != frameBytes) throw new IllegalArgumentException("PCM frame size");
    if (!lock.tryLock()) { contendedOffers.incrementAndGet(); return false; }
    try {
      expire(nowNs);
      if (size == frames.length) { remove(); dropped++; }
      int tail = (head + size) % frames.length;
      int start = src.position();
      try { src.get(frames[tail]); } finally { src.position(start); }
      arrivals[tail] = nowNs;
      size++;
      return true;
    } finally { lock.unlock(); }
  }

  /** Fill the complete requested region, using silence for missing audio, never old data. */
  public int read(ByteBuffer dest, long nowNs) {
    int start = dest.position(), length = dest.remaining();
    if (!lock.tryLock()) { contendedReads.incrementAndGet(); zero(dest, start, length); return 0; }
    try {
      expire(nowNs);
      int copied = 0;
      while (copied < length && size > 0) {
        int count = Math.min(length - copied, frameBytes - offset);
        dest.put(frames[head], offset, count);
        copied += count;
        offset += count;
        if (offset == frameBytes) remove();
      }
      zero(dest, start + copied, length - copied);
      if (copied < length) underflow++;
      return copied;
    } finally { dest.position(start); lock.unlock(); }
  }

  /** Control thread only; callers must stop accepting the old route before clearing. */
  public void clear() {
    lock.lock();
    try { head = size = offset = 0; } finally { lock.unlock(); }
  }

  /** Queued frames, expired/overflow frames, short reads, contended offers, contended reads. */
  public long[] snapshot() {
    lock.lock();
    try { return new long[]{size, dropped, underflow, contendedOffers.get(), contendedReads.get()}; }
    finally { lock.unlock(); }
  }

  private void expire(long nowNs) {
    while (size > 0 && nowNs - arrivals[head] > maxAgeNs) { remove(); dropped++; }
  }
  private void remove() { head = (head + 1) % frames.length; size--; offset = 0; }
  private static void zero(ByteBuffer b, int start, int count) {
    int previous = b.position();
    try {
      b.position(start);
      while (count > 0) {
        int n = Math.min(count, SILENCE.length);
        b.put(SILENCE, 0, n); count -= n;
      }
    } finally { b.position(previous); }
  }
}
