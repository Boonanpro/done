package app.done.dan.voice

import android.companion.AssociationInfo
import android.companion.AssociationRequest
import android.companion.BluetoothLeDeviceFilter
import android.companion.CompanionDeviceManager
import android.companion.CompanionDeviceService
import android.companion.ObservingDevicePresenceRequest
import android.app.Activity
import android.bluetooth.le.ScanFilter
import android.content.Context
import android.content.Intent
import android.content.IntentSender
import android.os.Build
import android.os.ParcelUuid
import androidx.core.content.ContextCompat
import java.util.UUID

/**
 * The pin as an Android companion device (2026-10-06). Once associated, Android itself watches for the pin and
 * starts this service when it comes near or powers on, even with the app killed, and a companion app may start its
 * foreground service and its screen from the background. So the standing link comes back without opening the app.
 */
class DanPinPresenceService : CompanionDeviceService() {
  override fun onDeviceAppeared(associationInfo: AssociationInfo) { appeared(associationInfo.deviceMacAddress?.toString()) }
  @Deprecated("API 31-32") override fun onDeviceAppeared(address: String) { appeared(address) }

  private fun appeared(address: String?) {
    android.util.Log.i("DanPinBle", "companion: pin appeared $address")
    if (address != null) DanPinLink.remember(this, address)
    startStanding(applicationContext)
  }

  companion object {
    private val AUDIO_SERVICE = UUID.fromString("19B10000-E8F2-537E-4F6C-D104768A1214")

    /** The standing link and the pin foreground service, from anywhere (system wake-up, app start, boot). */
    fun startStanding(ctx: Context) {
      DanPinLink.start(ctx)
      try {
        val intent = Intent(ctx, DanVoiceCallService::class.java).setAction("PIN")
        if (DanVoiceCallService.pinMode) ctx.startService(intent) else ContextCompat.startForegroundService(ctx, intent)
      } catch (e: Exception) { android.util.Log.w("DanPinBle", "pin service not started: $e") }
    }

    fun associated(ctx: Context): Boolean {
      val cdm = ctx.getSystemService(CompanionDeviceManager::class.java) ?: return false
      return if (Build.VERSION.SDK_INT >= 33) cdm.myAssociations.isNotEmpty() else @Suppress("DEPRECATION") cdm.associations.isNotEmpty()
    }

    /** Shows Android's one-time 「Done で ピン を管理しますか？」; afterwards the system watches the pin. */
    fun associate(activity: Activity, finished: (Boolean, String) -> Unit) {
      val cdm = activity.getSystemService(CompanionDeviceManager::class.java) ?: return finished(false, "no companion manager")
      if (associated(activity)) { observe(activity); return finished(true, "already") }
      // The pin advertises only while nothing is connected to it: free it for Android's search, reconnect after.
      DanPinLink.stop()
      var once = false
      val done = { ok: Boolean, detail: String -> if (!once) { once = true; DanPinLink.start(activity.applicationContext); finished(ok, detail) } }
      // Declining the dialog reports nothing back here: the link must not stay off.
      android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ done(false, "no answer") }, 90_000)
      val filter = BluetoothLeDeviceFilter.Builder()
        .setScanFilter(ScanFilter.Builder().setServiceUuid(ParcelUuid(AUDIO_SERVICE)).build()).build()
      val request = AssociationRequest.Builder().addDeviceFilter(filter).setSingleDevice(true).build()
      val callback = object : CompanionDeviceManager.Callback() {
        override fun onAssociationPending(sender: IntentSender) {
          try { activity.startIntentSenderForResult(sender, 7101, null, 0, 0, 0) } catch (e: Exception) { done(false, "$e") }
        }
        override fun onAssociationCreated(info: AssociationInfo) {
          info.deviceMacAddress?.let { DanPinLink.remember(activity, it.toString()) }
          observe(activity)
          android.util.Log.i("DanPinBle", "companion: associated ${info.deviceMacAddress}")
          done(true, "created")
        }
        @Deprecated("API < 33") override fun onDeviceFound(sender: IntentSender) { onAssociationPending(sender) }
        override fun onFailure(error: CharSequence?) { done(false, error?.toString() ?: "failed") }
      }
      if (Build.VERSION.SDK_INT >= 33) cdm.associate(request, ContextCompat.getMainExecutor(activity), callback)
      else @Suppress("DEPRECATION") cdm.associate(request, callback, null)
    }

    /** Asks Android to start [DanPinPresenceService] whenever the associated pin is near. Idempotent. */
    fun observe(ctx: Context) {
      val cdm = ctx.getSystemService(CompanionDeviceManager::class.java) ?: return
      try {
        if (Build.VERSION.SDK_INT >= 36) {
          for (a in cdm.myAssociations) cdm.startObservingDevicePresence(ObservingDevicePresenceRequest.Builder().setAssociationId(a.id).build())
        } else if (Build.VERSION.SDK_INT >= 33) {
          @Suppress("DEPRECATION") for (a in cdm.myAssociations) a.deviceMacAddress?.let { cdm.startObservingDevicePresence(it.toString()) }
        } else {
          @Suppress("DEPRECATION") for (address in cdm.associations) cdm.startObservingDevicePresence(address)
        }
      } catch (e: Exception) { android.util.Log.w("DanPinBle", "companion observe failed: $e") }
    }
  }
}
