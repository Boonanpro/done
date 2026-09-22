package app.done.dan.voice;

import java.util.UUID;

/** Process-wide reservation, acquired before opening microphones or starting a call service. */
public final class DanAudioLease {
  private static String token, mode;
  private DanAudioLease() {}
  public static synchronized String acquire(String requestedMode) {
    if (!"phone".equals(requestedMode) && !"relay".equals(requestedMode)) throw new IllegalArgumentException();
    if (token != null) throw new IllegalStateException("Another audio connection is active");
    mode = requestedMode;
    token = UUID.randomUUID().toString();
    return token;
  }
  public static synchronized String current(String expectedMode) {
    return expectedMode.equals(mode) ? token : null;
  }
  public static synchronized boolean owns(String expected) { return token != null && token.equals(expected); }
  public static synchronized void release(String expected) {
    if (owns(expected)) { token = null; mode = null; }
  }
}
