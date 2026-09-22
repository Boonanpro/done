import app.done.dan.voice.DanExternalAudio;
import java.nio.ByteBuffer;

public class DanExternalAudioTest {
  static ByteBuffer frame(int value) {
    ByteBuffer result = ByteBuffer.allocateDirect(960);
    for (int i = 0; i < 960; i++) result.put(i, (byte) value);
    return result;
  }
  static void all(ByteBuffer b, int value) {
    for (int i = 0; i < b.capacity(); i++) if (b.get(i) != (byte) value)
      throw new AssertionError("sample " + i + " = " + b.get(i));
  }
  public static void main(String[] args) {
    DanExternalAudio audio = new DanExternalAudio();
    ByteBuffer b = frame(17);
    if (audio.onBuffer(b, 2, 1, 48000, 960, 123) != 123) throw new AssertionError();
    all(b, 17); // Phone mic is unchanged until route activation.
    audio.onData(frame(34), 16, 48000, 1, 480, 0);
    long[] observed = audio.receivedFormat();
    if (!java.util.Arrays.equals(observed, new long[]{16,48000,1,480,960,1}))
      throw new AssertionError("phone route must observe remote sink format");
    if (audio.outputStats()[0] != 0) throw new AssertionError("phone route queued external playback");
    long first = audio.setExternal(true);
    audio.offerInput(first, frame(23));
    b.position(960); // Android AudioRecord can leave position at end of buffer.
    if (audio.onBuffer(b, 2, 1, 48000, 960, 123) != 0) throw new AssertionError();
    all(b, 23);
    if (b.position() != 960) throw new AssertionError("buffer position changed");
    audio.onBuffer(b, 2, 1, 48000, 960, 123); all(b, 0);
    audio.offerInput(first, frame(42)); audio.setMuted(true);
    if (audio.offerInput(first, frame(42))) throw new AssertionError("muted capture accepted");
    audio.onBuffer(b, 2, 1, 48000, 960, 123); all(b, 0);
    audio.setMuted(false);
    long second = audio.setExternal(true);
    if (audio.offerInput(first, frame(42))) throw new AssertionError("old socket accepted");
    audio.onData(frame(34), 16, 48000, 1, 480, 0);
    ByteBuffer out = frame(17);
    if (audio.readOutput(second, out) != 960) throw new AssertionError();
    all(out, 34);
    audio.onData(frame(34), 16, 48000, 1, 480, 0);
    audio.setExternal(false); audio.readOutput(second, out); all(out, 0);
    audio.setExternal(true);
    audio.onData(frame(34), 16, 16000, 1, 480, 0);
    audio.onBuffer(b, 2, 2, 48000, 960, 123); all(b, 0);
    if (audio.getFormatErrors() != 2) throw new AssertionError();
    // SDK calls without a physical AudioRecord have bytesRead=0 and no clock.
    // They must consume real time, including during silence/mute, not flood RTP.
    audio.setMuted(true);
    long started = System.nanoTime();
    for (int i = 0; i < 20; i++) audio.onBuffer(b, 2, 1, 48000, 0, 0);
    long elapsed = System.nanoTime() - started;
    if (elapsed < 190_000_000L || elapsed > 2_000_000_000L)
      throw new AssertionError("external capture clock: " + elapsed);
    all(b, 0);
    System.out.println("PASS: native passthrough, external PCM, mute, generation, output, format validation");
  }
}
