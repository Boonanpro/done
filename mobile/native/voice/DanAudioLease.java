package app.done.dan.voice;

import java.util.UUID;

/** Process-wide reservation, acquired before opening microphones or starting a call service. */
public final class DanAudioLease {
  private static String token, mode;
  private DanAudioLease() {}
  public static String acquire(String requestedMode) {
    String issued;
    synchronized (DanAudioLease.class) {
      if (!"phone".equals(requestedMode) && !"relay".equals(requestedMode)) throw new IllegalArgumentException();
      if (token != null) throw new IllegalStateException("Another audio connection is active");
      mode = requestedMode;
      token = UUID.randomUUID().toString();
      issued = token;
    }
    DanPhoneLifelog.leaseChanged(true);   // the phone's own recording pauses for the call
    return issued;
  }
  public static synchronized String current(String expectedMode) {
    return expectedMode.equals(mode) ? token : null;
  }
  public static synchronized boolean owns(String expected) { return token != null && token.equals(expected); }
  /** True while a call (phone or relay) holds the audio. */
  public static synchronized boolean active() { return token != null; }
  public static void release(String expected) {
    boolean released = false;
    synchronized (DanAudioLease.class) {
      if (owns(expected)) { token = null; mode = null; released = true; }
    }
    if (released) DanPhoneLifelog.leaseChanged(false);
  }
}
