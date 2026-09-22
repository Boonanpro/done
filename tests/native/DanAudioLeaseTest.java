import app.done.dan.voice.DanAudioLease;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public class DanAudioLeaseTest {
  public static void main(String[] args) throws Exception {
    String phone = DanAudioLease.acquire("phone");
    try {
      try { DanAudioLease.acquire("relay"); throw new AssertionError("Double owner"); }
      catch (IllegalStateException expected) {}
      DanAudioLease.release("stale");
      if (!DanAudioLease.owns(phone)) throw new AssertionError("Stale release ended call");
    } finally { DanAudioLease.release(phone); }
    String relay = DanAudioLease.acquire("relay");
    DanAudioLease.release(phone);
    if (!DanAudioLease.owns(relay) || phone.equals(relay)) throw new AssertionError("Old call released new call");
    DanAudioLease.release(relay);
    CountDownLatch start = new CountDownLatch(1);
    AtomicInteger acquired = new AtomicInteger();
    AtomicReference<String> winner = new AtomicReference<>();
    Thread[] attempts = new Thread[2];
    for (int i=0;i<2;i++) {
      final String mode = i==0 ? "phone" : "relay";
      attempts[i] = new Thread(() -> {
        try { start.await(); winner.set(DanAudioLease.acquire(mode)); acquired.incrementAndGet(); }
        catch (IllegalStateException expected) {}
        catch (InterruptedException e) { throw new AssertionError(e); }
      });
      attempts[i].start();
    }
    start.countDown();
    for (Thread attempt : attempts) attempt.join(1000);
    try {
      if(acquired.get()!=1) throw new AssertionError("Concurrent acquisition count="+acquired.get());
    } finally { DanAudioLease.release(winner.get()); }
    System.out.println("PASS: single audio owner, stale release, generation identity, concurrent acquisition");
  }
}
