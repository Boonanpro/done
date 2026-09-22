package app.done.dan.voice;

import java.io.DataInputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.locks.LockSupport;

/** A single local DAN4 connection. No cloud relay, reconnection, or Live session ownership. */
public final class DanAtomSocket implements AutoCloseable {
  public interface Listener {
    // These callbacks run on the reader/writer thread; enqueue UI/session work elsewhere.
    void intent(boolean requested, int boot, int revision);
    void closed(String reason);
  }
  private static final long FRAME_NS = 10_000_000L, STALE_NS = 1_000_000_000L;
  private final DanExternalAudio endpoint;
  private final Listener listener;
  private final AtomicBoolean running = new AtomicBoolean();
  private final AtomicBoolean started = new AtomicBoolean();
  private final Object controlLock = new Object();
  private volatile Socket socket;
  private volatile Header header;
  private volatile long routeToken = -1, writtenAt;
  private volatile boolean ready;
  private volatile boolean remoteCues;
  private volatile long endDeadline;
  private Command command;

  private static final class Header {
    final int flags, boot, revision;
    final long at;
    Header(int flags, int boot, int revision) {
      this.flags = flags; this.boot = boot; this.revision = revision; at = System.nanoTime();
    }
    boolean requested() { return (flags & 1) != 0; }
  }
  private static final class Command {
    final Header expected;
    final boolean wanted;
    Command(Header expected, boolean wanted) { this.expected = expected; this.wanted = wanted; }
    boolean matches(Header value) { return expected.boot == value.boot && expected.revision == value.revision; }
  }

  public DanAtomSocket(DanExternalAudio endpoint, Listener listener) {
    this.endpoint = endpoint; this.listener = listener;
  }

  public void start(String host, int port, String pairingKey) {
    if (!pairingKey.matches("[0-9a-fA-F]{32}")) throw new IllegalArgumentException("Invalid pairing key");
    if (!started.compareAndSet(false, true)) throw new IllegalStateException("Socket already started");
    running.set(true);
    Thread reader = new Thread(() -> connect(host, port, pairingKey), "DanAtomLocalRead");
    reader.setDaemon(true); reader.start();
  }

  /** The call/route owner supplies the current endpoint generation; the socket never changes it. */
  public void setRoute(long token, boolean callReady) { routeToken = token; ready = callReady; }

  public boolean supportsRemoteCues() { Header current = header; return current != null && (current.flags & 32) != 0; }
  /** Only advertised firmware receives this extension; old devices keep local cues. */
  public void setRemoteCues(boolean enabled) { remoteCues = enabled; }

  public boolean requestWanted(boolean wanted) {
    synchronized (controlLock) {
      Header current = header;
      if (!running.get() || current == null || System.nanoTime() - current.at > STALE_NS) return false;
      command = current.requested() == wanted ? null : new Command(current, wanted);
      return true;
    }
  }

  /** Send STOP and await its acknowledgement on socket threads, bounded to half a second. */
  public void finish() {
    ready = false;
    if (!requestWanted(false)) { close(); return; }
    endDeadline = System.nanoTime() + 500_000_000L;
  }

  private void connect(String host, int port, String key) {
    try {
      Socket tcp = new Socket(); socket = tcp;
      if (!running.get()) { tcp.close(); return; }
      tcp.setTcpNoDelay(true); tcp.setSoTimeout(1000);
      tcp.connect(new InetSocketAddress(host, port), 2000);
      tcp.getOutputStream().write(("DAN4" + key).getBytes(StandardCharsets.US_ASCII));
      DataInputStream input = new DataInputStream(tcp.getInputStream());
      byte[] hello = new byte[4]; input.readFully(hello);
      if (!"OKF4".equals(new String(hello, StandardCharsets.US_ASCII))) throw new IOException("Handshake");
      writtenAt = System.nanoTime();
      Thread writer = new Thread(() -> write(tcp), "DanAtomLocalWrite");
      writer.setDaemon(true); writer.start();
      byte[] frame = new byte[972];
      ByteBuffer packet = ByteBuffer.wrap(frame).order(ByteOrder.LITTLE_ENDIAN);
      ByteBuffer pcm = ByteBuffer.wrap(frame, 12, 960).slice();
      while (running.get()) {
        input.readFully(frame);
        if (System.nanoTime() - writtenAt > STALE_NS) throw new IOException("Output stalled");
        Header next = new Header(packet.getInt(0), packet.getInt(4), packet.getInt(8));
        Header previous;
        boolean shouldFinish;
        synchronized (controlLock) {
          previous = header; header = next;
          if (command != null && !command.matches(next)) command = null;
          shouldFinish = endDeadline != 0 && (!next.requested() || command == null);
        }
        if (shouldFinish) {
          terminate("ended"); return;
        }
        if (next.requested() && ready) endpoint.offerInput(routeToken, pcm);
        if (previous == null || previous.flags != next.flags || previous.boot != next.boot
            || previous.revision != next.revision) listener.intent(next.requested(), next.boot, next.revision);
      }
    } catch (Exception e) { terminate("local_connection_failed"); }
  }

  private void write(Socket tcp) {
    byte[] frame = new byte[972];
    ByteBuffer packet = ByteBuffer.wrap(frame).order(ByteOrder.LITTLE_ENDIAN);
    ByteBuffer pcm = ByteBuffer.wrap(frame, 12, 960).slice();
    long deadline = System.nanoTime();
    try {
      while (running.get()) {
        if (endDeadline != 0 && System.nanoTime() >= endDeadline) { terminate("end_timeout"); return; }
        Header current; Command pending;
        synchronized (controlLock) { current = header; pending = command; }
        if (current != null) {
          if (System.nanoTime() - current.at > STALE_NS) throw new IOException("Input stalled");
          int flags = ready && current.requested() ? 1 : 0;
          if (pending != null && pending.matches(current)) flags = pending.wanted ? 4 : 2;
          int wireFlags = flags | (remoteCues && (current.flags & 32) != 0 ? 16 : 0);
          packet.putInt(0, wireFlags); packet.putInt(4, current.boot); packet.putInt(8, current.revision);
          if (flags == 1) endpoint.readOutput(routeToken, pcm);
          else for (int i = 12; i < frame.length; i++) frame[i] = 0;
          tcp.getOutputStream().write(frame);
        }
        writtenAt = System.nanoTime();
        deadline += FRAME_NS;
        if (deadline < writtenAt) deadline = writtenAt + FRAME_NS; // Never replay a catch-up burst.
        LockSupport.parkNanos(deadline - writtenAt);
      }
    } catch (Exception e) { terminate("local_output_failed"); }
  }

  private void terminate(String reason) {
    if (!running.compareAndSet(true, false)) return;
    ready = false;
    try { Socket active = socket; if (active != null) active.close(); } catch (IOException ignored) {}
    listener.closed(reason);
  }
  @Override public void close() { terminate("closed"); }
}
