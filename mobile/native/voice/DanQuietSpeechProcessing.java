package app.done.dan.voice;

import java.nio.ByteBuffer;
import org.webrtc.ExternalAudioProcessingFactory;

/**
 * Capture post-processing: runs on the microphone after WebRTC's echo cancellation, the same place the dashboard lifts a
 * whisper (after the browser's echo cancellation). On only while a phone-owned call captures from Bluetooth earbuds.
 */
final class DanQuietSpeechProcessing implements ExternalAudioProcessingFactory.AudioProcessing {
  private volatile boolean enabled;
  private DanQuietSpeechLift lift; // audio thread only

  void setEnabled(boolean value) { enabled = value; }

  @Override public void initialize(int sampleRateHz, int numChannels) { lift = new DanQuietSpeechLift(sampleRateHz); }

  @Override public void reset(int sampleRateHz) { lift = new DanQuietSpeechLift(sampleRateHz); }

  /** buffer: the first channel's full band, numFrames float samples in 16-bit scale, native byte order. */
  @Override public void process(int numBands, int numFrames, ByteBuffer buffer) {
    DanQuietSpeechLift current = lift;
    if (current == null) return;
    if (!enabled) { current.reset(); return; }
    current.processFloat(buffer, numFrames);
  }
}
