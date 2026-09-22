import app.done.dan.voice.DanPcmQueue;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

public class DanPcmQueueTest {
  static void equal(byte[] actual, int... expected) {
    byte[] bytes = new byte[expected.length];
    for (int i = 0; i < expected.length; i++) bytes[i] = (byte) expected[i];
    if (!Arrays.equals(actual, bytes)) throw new AssertionError(Arrays.toString(actual));
  }
  public static void main(String[] args) throws Exception {
    DanPcmQueue q = new DanPcmQueue(4, 2, 100);
    ByteBuffer source = ByteBuffer.wrap(new byte[]{1, 2, 3, 4});
    q.offer(source, 0); source.put(0, (byte) 99);
    ByteBuffer partial = ByteBuffer.allocate(2);
    q.read(partial, 1); equal(partial.array(), 1, 2);
    if (source.position() != 0 || partial.position() != 0) throw new AssertionError("positions changed");
    q.offer(ByteBuffer.wrap(new byte[]{5, 6, 7, 8}), 2);
    q.offer(ByteBuffer.wrap(new byte[]{9, 10, 11, 12}), 3);
    ByteBuffer out = ByteBuffer.allocate(10);
    if (q.read(out, 4) != 8) throw new AssertionError();
    equal(out.array(), 5, 6, 7, 8, 9, 10, 11, 12, 0, 0);
    q.offer(source, 5); q.read(out, 106);
    equal(out.array(), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    q.offer(source, 107); q.clear(); q.read(out, 108);
    equal(out.array(), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    // Native callers use sliced/direct buffers with nonzero positions. Bulk
    // copying must preserve both positions and bytes outside the requested span.
    ByteBuffer positioned = ByteBuffer.allocateDirect(8);
    positioned.put(new byte[]{99,98,1,2,3,4,97,96}).position(2).limit(6);
    q.offer(positioned, 109);
    ByteBuffer bounded = ByteBuffer.wrap(new byte[]{9,9,9,9,9,9,9,9});
    bounded.position(1).limit(7);
    q.read(bounded, 110);
    equal(bounded.array(), 9,1,2,3,4,0,0,9);
    if(positioned.position()!=2 || positioned.limit()!=6 || bounded.position()!=1 || bounded.limit()!=7)
      throw new AssertionError("bulk copy changed buffer boundaries");
    // Socket bursts and audio callbacks running concurrently must not deadlock or leak storage.
    DanPcmQueue stress = new DanPcmQueue(960, 6, 80_000_000L);
    Thread writer = new Thread(() -> {
      ByteBuffer frame = ByteBuffer.allocate(960);
      for (int i = 0; i < 20000; i++) stress.offer(frame, System.nanoTime());
    });
    writer.start();
    ByteBuffer frame = ByteBuffer.allocateDirect(960);
    for (int i = 0; i < 20000; i++) stress.read(frame, System.nanoTime());
    writer.join(5000);
    if (writer.isAlive() || stress.snapshot()[0] > 6) throw new AssertionError("unbounded or blocked");
    contention();
    System.out.println("PASS: PCM ownership, partial frames, overflow, expiry, silence, reset, concurrency, contention accounting");
  }

  static void contention() throws Exception {
    DanPcmQueue queue = new DanPcmQueue(4, 2, 100);
    var field = DanPcmQueue.class.getDeclaredField("lock");
    field.setAccessible(true);
    ReentrantLock lock = (ReentrantLock) field.get(queue);
    CountDownLatch finished = new CountDownLatch(1);
    ByteBuffer out = ByteBuffer.wrap(new byte[]{9,9,9,9});
    boolean[] accepted = {true};
    int[] copied = {-1};
    Thread callback = new Thread(() -> {
      accepted[0] = queue.offer(ByteBuffer.allocate(4), 0);
      copied[0] = queue.read(out, 0);
      finished.countDown();
    });
    lock.lock();
    try {
      callback.start();
      // It must finish while the competing lock is STILL held, not wait then appear fast.
      if (!finished.await(1, TimeUnit.SECONDS)) throw new AssertionError("Audio callback waited on lock");
    } finally { lock.unlock(); callback.join(1000); }
    if (accepted[0] || copied[0] != 0) throw new AssertionError("Contended access succeeded");
    equal(out.array(),0,0,0,0);
    long[] stats = queue.snapshot();
    if (stats[3] != 1 || stats[4] != 1) throw new AssertionError("Contention was invisible");
  }
}
