import app.done.dan.voice.DanAtomSocket;
import app.done.dan.voice.DanExternalAudio;
import java.io.DataInputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public class DanAtomSocketTest {
  static byte[] packet(int flags, int revision, int pcm) {
    byte[] bytes = new byte[972];
    ByteBuffer b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
    b.putInt(flags).putInt(123).putInt(revision);
    for (int i=12; i<bytes.length; i++) bytes[i]=(byte)pcm;
    return bytes;
  }
  static ByteBuffer receive(DataInputStream in, int flags, int revision) throws Exception {
    for (int i=0;i<30;i++) {
      byte[] bytes = new byte[972]; in.readFully(bytes);
      ByteBuffer b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
      if (b.getInt(0)==flags && b.getInt(8)==revision) return b;
    }
    throw new AssertionError("Expected flags="+flags+" revision="+revision);
  }
  public static void main(String[] args) throws Exception {
    DanExternalAudio endpoint = new DanExternalAudio();
    long token = endpoint.setExternal(true);
    CountDownLatch intent = new CountDownLatch(1), closed = new CountDownLatch(1);
    AtomicInteger closeCount = new AtomicInteger();
    DanAtomSocket client = new DanAtomSocket(endpoint, new DanAtomSocket.Listener() {
      public void intent(boolean wanted,int boot,int revision) { intent.countDown(); }
      public void closed(String reason) {closeCount.incrementAndGet(); closed.countDown();}
    });
    try (ServerSocket server = new ServerSocket(0)) {
      server.setSoTimeout(2000);
      client.setRoute(token,true);
      client.start("127.0.0.1",server.getLocalPort(),"00000000000000000000000000000000");
      try (Socket peer = server.accept()) {
        peer.setSoTimeout(2000);
        DataInputStream input = new DataInputStream(peer.getInputStream());
        byte[] hello = new byte[36]; input.readFully(hello);
        if (!new String(hello, StandardCharsets.US_ASCII).equals("DAN400000000000000000000000000000000")) throw new AssertionError();
        peer.getOutputStream().write("OKF4".getBytes(StandardCharsets.US_ASCII));
        // TCP may fragment a frame; the client must not interpret a partial header/PCM.
        byte[] first = packet(1,7,23);
        peer.getOutputStream().write(first,0,19);
        peer.getOutputStream().write(first,19,first.length-19);
        if (!intent.await(500,TimeUnit.MILLISECONDS)) throw new AssertionError("No intent");
        ByteBuffer captured = ByteBuffer.allocateDirect(960);
        endpoint.onBuffer(captured,2,1,48000,960,0);
        for(int i=0;i<960;i++) if(captured.get(i)!=23) throw new AssertionError("Input PCM");
        ByteBuffer audio = ByteBuffer.allocateDirect(960);
        for(int i=0;i<960;i++) audio.put(i,(byte)34);
        endpoint.onData(audio,16,48000,1,480,0);
        boolean heard=false;
        for(int n=0;n<10;n++) {
          ByteBuffer b=receive(input,1,7);
          if(b.get(12)==34) {heard=true; break;}
        }
        if(!heard) throw new AssertionError("Output PCM");
        if(!client.requestWanted(false)) throw new AssertionError("STOP refused");
        ByteBuffer stop = receive(input,2,7);
        for(int i=12;i<972;i++) if(stop.get(i)!=0) throw new AssertionError("STOP emitted audio");
        // A physical revision change supersedes the pending stop. Never apply STOP to the new intent.
        peer.getOutputStream().write(packet(1,8,0));
        receive(input,1,8);
        peer.getOutputStream().write(packet(0,9,0));
        receive(input,0,9);
        // Silent/missing device traffic must close transport rather than hold it forever.
        if(!closed.await(1800,TimeUnit.MILLISECONDS)) throw new AssertionError("Stalled input stayed open");
        client.close();
        if(closeCount.get()!=1) throw new AssertionError("Duplicate closure");
      }
    } finally {client.close();}
    rejectedHandshake();
    gracefulStop(true);
    gracefulStop(false);
    remoteCueOwnership(true);
    remoteCueOwnership(false);
    System.out.println("PASS: DAN4 handshake, TCP fragmentation, bidirectional PCM, STOP CAS, stale input, single close, rejected handshake");
  }

  static void remoteCueOwnership(boolean supported) throws Exception {
    CountDownLatch ready = new CountDownLatch(1), closed = new CountDownLatch(1);
    DanAtomSocket client = new DanAtomSocket(new DanExternalAudio(), new DanAtomSocket.Listener() {
      public void intent(boolean requested,int boot,int revision) {ready.countDown();}
      public void closed(String reason) {closed.countDown();}
    });
    try (ServerSocket server = new ServerSocket(0)) {
      server.setSoTimeout(2000);
      client.setRemoteCues(true);
      client.start("127.0.0.1",server.getLocalPort(),"00000000000000000000000000000000");
      try (Socket peer = server.accept()) {
        peer.setSoTimeout(2000);
        DataInputStream input = new DataInputStream(peer.getInputStream());
        input.readFully(new byte[36]);
        peer.getOutputStream().write("OKF4".getBytes(StandardCharsets.US_ASCII));
        int capability = supported ? 32 : 0, cueOwner = supported ? 16 : 0;
        peer.getOutputStream().write(packet(capability,7,0));
        if (!ready.await(500,TimeUnit.MILLISECONDS)) throw new AssertionError("No capability header");
        if (client.supportsRemoteCues()!=supported) throw new AssertionError("Incorrect capability");
        if (!client.requestWanted(true)) throw new AssertionError("START refused");
        receive(input,4|cueOwner,7);
        client.setRoute(-1,true);
        peer.getOutputStream().write(packet(capability|1,8,0));
        receive(input,1|cueOwner,8);
        client.finish();
        ByteBuffer stop = receive(input,2|cueOwner,8);
        for(int i=12;i<972;i++) if(stop.get(i)!=0) throw new AssertionError("Cue owner flag emitted stale PCM");
        peer.getOutputStream().write(packet(capability,9,0));
        if(!closed.await(700,TimeUnit.MILLISECONDS)) throw new AssertionError("STOP did not close");
      }
    } finally {client.close();}
  }

  static void gracefulStop(boolean acknowledge) throws Exception {
    CountDownLatch ready = new CountDownLatch(1), closed = new CountDownLatch(1);
    DanAtomSocket client = new DanAtomSocket(new DanExternalAudio(), new DanAtomSocket.Listener() {
      public void intent(boolean requested,int boot,int revision) {ready.countDown();}
      public void closed(String reason) {closed.countDown();}
    });
    try (ServerSocket server = new ServerSocket(0)) {
      server.setSoTimeout(2000);
      client.start("127.0.0.1",server.getLocalPort(),"00000000000000000000000000000000");
      try(Socket peer=server.accept()) {
        peer.setSoTimeout(2000);
        DataInputStream in=new DataInputStream(peer.getInputStream());
        in.readFully(new byte[36]);
        peer.getOutputStream().write("OKF4".getBytes(StandardCharsets.US_ASCII));
        peer.getOutputStream().write(packet(1,11,0));
        if(!ready.await(500,TimeUnit.MILLISECONDS)) throw new AssertionError("No device intent");
        client.finish();
        receive(in,2,11); // STOP must actually reach the wire before close.
        if(acknowledge) peer.getOutputStream().write(packet(0,12,0));
        if(!closed.await(800,TimeUnit.MILLISECONDS)) throw new AssertionError("End did not settle");
      }
    } finally {client.close();}
  }

  static void rejectedHandshake() throws Exception {
    CountDownLatch closed = new CountDownLatch(1);
    AtomicInteger intents = new AtomicInteger(), closures = new AtomicInteger();
    DanAtomSocket client = new DanAtomSocket(new DanExternalAudio(), new DanAtomSocket.Listener() {
      public void intent(boolean requested, int boot, int revision) {intents.incrementAndGet();}
      public void closed(String reason) {closures.incrementAndGet(); closed.countDown();}
    });
    try (ServerSocket server = new ServerSocket(0)) {
      server.setSoTimeout(2000);
      client.start("127.0.0.1",server.getLocalPort(),"00000000000000000000000000000000");
      try (Socket peer = server.accept()) {
        peer.setSoTimeout(1000);
        DataInputStream in = new DataInputStream(peer.getInputStream());
        in.readFully(new byte[36]);
        peer.getOutputStream().write("NOPE".getBytes(StandardCharsets.US_ASCII));
        if(!closed.await(1000,TimeUnit.MILLISECONDS)) throw new AssertionError("Bad handshake held connection");
        if(in.read()!=-1 || intents.get()!=0) throw new AssertionError("Audio/intent after rejected handshake");
        if(client.requestWanted(true)) throw new AssertionError("Command accepted after failure");
        client.close();
        if(closures.get()!=1) throw new AssertionError("Duplicate failure closure");
      }
    } finally {client.close();}
  }
}
