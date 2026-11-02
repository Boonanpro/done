package app.done.dan.voice

import android.app.Activity
import android.os.Bundle
import android.os.SystemClock
import android.content.Intent
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.modules.core.DeviceEventManagerModule
import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicLong

/** An explicit launcher entry; no browser/deep-link filter can trigger a call. */
class DanVoiceShortcutActivity : Activity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    if (savedInstanceState == null) {
      DanVoiceShortcut.requested.set(SystemClock.elapsedRealtime())
      startActivity(Intent().setClassName(packageName, "app.done.dan.MainActivity")
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
      DanVoiceShortcut.context?.get()?.let { react ->
        if (react.hasActiveReactInstance()) react.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
          .emit("DanVoiceShortcut", null)
      }
    }
    finish()
  }
}

object DanVoiceShortcut {
  val requested = AtomicLong(0)
  var context: WeakReference<ReactApplicationContext>? = null
  fun take(): Boolean {
    val at = requested.getAndSet(0)
    return at > 0 && SystemClock.elapsedRealtime() - at < 30000
  }
}
