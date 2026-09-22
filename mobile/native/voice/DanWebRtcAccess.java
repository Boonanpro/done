package com.oney.WebRTCModule;

/** Access the same executor as peer creation/disposal without reflection or a second queue. */
public final class DanWebRtcAccess {
  private DanWebRtcAccess() {}
  public static void execute(Runnable task) { ThreadUtils.runOnExecutor(task); }
  public static org.webrtc.audio.AudioProcessingState processingState(WebRTCModule module) {
    return module.mFactory.getAudioProcessingState();
  }
}
