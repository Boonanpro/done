package app.done.dan.voice

import android.app.Activity
import android.app.Application
import android.os.Bundle
import android.os.SystemClock
import android.content.Intent
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.modules.core.DeviceEventManagerModule
import java.lang.ref.WeakReference
import java.util.concurrent.atomic.AtomicReference
import com.facebook.react.bridge.Arguments

/** An explicit launcher entry; no browser/deep-link filter can trigger a call. */
class DanVoiceShortcutActivity : Activity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    if (savedInstanceState == null) {
      DanVoiceShortcut.request()
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
  private data class Request(val at: Long, val preserveScreen: Boolean)
  private val requested = AtomicReference<Request?>(null)
  private val visibleMainActivities = mutableSetOf<Activity>()
  private var installed = false
  var context: WeakReference<ReactApplicationContext>? = null
  // Started, rather than resumed: Samsung's dialog-style helper pauses the chat
  // before forwarding here. A background MainActivity has already been stopped.
  fun install(app: Application) {
    if (installed) return
    installed = true
    app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
      override fun onActivityStarted(activity: Activity) {
        if (activity.javaClass.name == "app.done.dan.MainActivity") visibleMainActivities.add(activity)
      }
      override fun onActivityStopped(activity: Activity) { visibleMainActivities.remove(activity) }
      override fun onActivityDestroyed(activity: Activity) { visibleMainActivities.remove(activity) }
      override fun onActivityCreated(activity: Activity, state: Bundle?) {}
      override fun onActivityResumed(activity: Activity) {}
      override fun onActivityPaused(activity: Activity) {}
      override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) {}
    })
  }
  fun request() {
    val preserve = visibleMainActivities.isNotEmpty()
    requested.set(Request(SystemClock.elapsedRealtime(), preserve))
    android.util.Log.i("DanVoiceShortcut", "preserveScreen=$preserve")
  }
  fun take(): com.facebook.react.bridge.WritableMap? {
    val request = requested.getAndSet(null) ?: return null
    if (SystemClock.elapsedRealtime() - request.at >= 30000) return null
    return Arguments.createMap().apply { putBoolean("preserveScreen", request.preserveScreen) }
  }
}
