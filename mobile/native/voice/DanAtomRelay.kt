package app.done.dan.voice

import android.content.Context
import android.media.*
import android.os.Handler
import android.os.Looper
import com.facebook.react.bridge.*
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.net.Socket
import java.net.InetSocketAddress
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** The phone switches PCM endpoints. It never owns/restarts the Live conversation. */
object DanAtomRelay {
  private var audioLease: String? = null
  private var context: Context? = null
  private var manager: AudioManager? = null
  private val running = AtomicBoolean(false)
  private val generation = AtomicInteger(0)
  private var socket: Socket? = null
  private var websocket: WebSocket? = null
  private var client: OkHttpClient? = null
  @Volatile private var record: AudioRecord? = null
  private var playback: AudioTrack? = null
  private var focus: AudioFocusRequest? = null
  private var callback: AudioDeviceCallback? = null
  private var modeListener: AudioManager.OnModeChangedListener? = null
  private var takingAudio = false
  private var ownsCommunication = false
  @Volatile private var headset = false
  @Volatile private var requested = false
  @Volatile private var callConnected = false
  @Volatile private var phoneCall = false
  @Volatile private var paused = false
  @Volatile private var route = "atom"
  @Volatile private var state = "off"
  @Volatile private var received = 0L
  @Volatile private var dropped = 0L
  @Volatile private var sharingMedia = false
  @Volatile private var deviceHeader = ByteArray(12)
  @Volatile private var deviceFrameAt = 0L
  @Volatile private var endRequested = false
  @Volatile private var endRequestedAt = 0L
  @Volatile private var micMuted = false
  @Volatile private var callStartedAt = 0L
  fun endCall() {
    if(!running.get()) return
    endRequested=true;endRequestedAt=android.os.SystemClock.elapsedRealtime()
  }
  fun muteMicrophone(value:Boolean) {micMuted=value}
  private val lock = Any()
  fun callActive() = running.get() && callConnected
  fun audioPaused() = running.get() && paused
  fun resumeAudio() {
    if(!running.get() || phoneCall) return
    synchronized(lock) { releaseAudio();paused=false }
    refreshRoute()
  }
  fun status() = Arguments.createMap().apply {
    putBoolean("enabled",running.get()); putString("state",state); putString("route",route)
    putBoolean("requested",requested); putBoolean("headset",headset); putDouble("frames",received.toDouble())
    putDouble("droppedFrames",dropped.toDouble())
    putBoolean("connected",callConnected);putBoolean("paused",paused);putBoolean("phoneCall",phoneCall)
    putBoolean("sharingMedia",sharingMedia)
    putBoolean("ending",endRequested);putBoolean("muted",micMuted)
    putDouble("startedAt",callStartedAt.toDouble())
  }
  fun start(ctx: Context, base: String, token: String, host: String, key: String, lease: String) {
    check(!running.get()) { "Atom relay is already active" }
    require(base.startsWith("https://") && key.matches(Regex("[a-f0-9]{32}")))
    audioLease=lease
    context=ctx.applicationContext; manager=ctx.getSystemService(AudioManager::class.java)
    running.set(true); state="connecting"; received=0; dropped=0
    val epoch=generation.incrementAndGet()
    val devices = object: AudioDeviceCallback() {
      override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = refreshRoute()
      override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = refreshRoute()
    }
    callback=devices; manager!!.registerAudioDeviceCallback(devices,Handler(Looper.getMainLooper()))
    modeListener=AudioManager.OnModeChangedListener { mode ->
      if(mode==AudioManager.MODE_IN_CALL || (mode==AudioManager.MODE_IN_COMMUNICATION && !ownsCommunication && !takingAudio)) {
        phoneCall=true;paused=true; synchronized(lock) {releaseAudio(true);route="atom"}
      } else if(mode==AudioManager.MODE_NORMAL && phoneCall) {phoneCall=false;paused=false;refreshRoute()}
    }
    manager!!.addOnModeChangedListener(ctx.mainExecutor,modeListener!!)
    client=OkHttpClient.Builder().readTimeout(0,TimeUnit.MILLISECONDS).pingInterval(15,TimeUnit.SECONDS).build()
    val request=Request.Builder().url(base.replaceFirst("https://","wss://")+"/api/v1/voicelog/atom-relay")
      .header("Authorization","Bearer $token").build()
    websocket=client!!.newWebSocket(request,object: WebSocketListener() {
      override fun onMessage(ws:WebSocket,text:String) {
        if(generation.get()!=epoch) return
        if (JSONObject(text).optString("type")=="ready") Thread({connectDevice(host,key,epoch)},"DanAtomPcm").start()
      }
      override fun onMessage(ws:WebSocket,bytes:ByteString) {
        if (!running.get() || generation.get()!=epoch) return
        val data=bytes.toByteArray()
        if(data.size!=972) { fail("invalid_frame",epoch);return }
        callConnected=(data[0].toInt() and 1)!=0
        if(callConnected && callStartedAt==0L)callStartedAt=System.currentTimeMillis()
        if(!requested)callStartedAt=0L
        if(endRequested) {
          // Device intent is authoritative. Repeated compare-and-set STOP
          // headers end the existing Live session without dropping the relay.
          deviceHeader.copyInto(data,0,0,12);data[0]=2
          java.util.Arrays.fill(data,12,972,0.toByte())
        }
        try {
          synchronized(lock) {
            if(route=="headset" && !paused) playback?.write(data,12,960,AudioTrack.WRITE_NON_BLOCKING)
            // Phone calls suspend Dan. The Atom receives the same state header,
            // but no audible output when the headset/telephone owns the route.
            if(route=="headset" || paused) java.util.Arrays.fill(data,12,972,0.toByte())
            socket?.getOutputStream()?.write(data)
          }
        } catch(e:Exception) { fail("device_write_failed",epoch) }
      }
      override fun onFailure(ws:WebSocket,t:Throwable,response:Response?) { fail("network_disconnected",epoch) }
      override fun onClosed(ws:WebSocket,code:Int,reason:String) { if(running.get()) fail("relay_closed",epoch) }
    })
  }
  private fun connectDevice(host:String,key:String,epoch:Int) {
    try {
      val tcp=Socket(); tcp.tcpNoDelay=true; tcp.soTimeout=6000
      tcp.connect(InetSocketAddress(host,48800),5000)
      if(generation.get()!=epoch) {tcp.close();return}
      socket=tcp
      tcp.getOutputStream().write(("DAN4"+key).toByteArray(Charsets.US_ASCII))
      val input=java.io.DataInputStream(tcp.getInputStream())
      val hello=ByteArray(4);input.readFully(hello)
      check(String(hello,Charsets.US_ASCII)=="OKF4")
      state="connected";refreshRoute()
      while(running.get() && generation.get()==epoch) {
        val frame=ByteArray(972);input.readFully(frame)
        deviceHeader=frame.copyOfRange(0,12)
        deviceFrameAt=android.os.SystemClock.elapsedRealtime()
        val wanted=(frame[0].toInt() and 1)!=0
        if(!wanted) {endRequested=false;callStartedAt=0L}
        if(endRequested && android.os.SystemClock.elapsedRealtime()-endRequestedAt>5000) {
          endRequested=false;state="end_failed"
        }
        if(wanted!=requested) { requested=wanted;refreshRoute() }
        synchronized(lock) {
          if(paused || micMuted || endRequested) java.util.Arrays.fill(frame,12,972,0.toByte())
        }
        // Bluetooth capture owns its own clock. Atom's Wi-Fi timing must not
        // decide when the headset microphone is drained.
        if(route!="headset") sendFrame(frame)
        received++
      }
    } catch(e:Exception) {
      android.util.Log.w("DanAtomRelay", "device loop failed: ${e.javaClass.simpleName}; frames=$received")
      if(running.get()) fail("atom_unreachable",epoch)
    }
  }
  private fun sendFrame(frame:ByteArray) {
    val ws=websocket ?: return
    if(ws.queueSize()>972*12) {dropped++;return}
    if(!ws.send(ByteString.of(*frame))) throw IllegalStateException("Audio relay closed")
  }
  private fun captureHeadset(capture:AudioRecord) {
    val epoch=generation.get()
    Thread({
      android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO)
      var frames=0;var energy=0.0;var samples=0L
      var reportAt=android.os.SystemClock.elapsedRealtime()
      try {
        while(running.get() && generation.get()==epoch && record===capture && route=="headset") {
          val frame=ByteArray(972);var offset=12
          while(offset<972 && record===capture) {
            val n=capture.read(frame,offset,972-offset,AudioRecord.READ_BLOCKING)
            if(n<=0) throw IllegalStateException("Headset capture failed")
            offset+=n
          }
          if(record!==capture || paused || route!="headset") break
          // Never keep an old device intent alive after physical disconnection.
          if(android.os.SystemClock.elapsedRealtime()-deviceFrameAt>1000) continue
          deviceHeader.copyInto(frame)
          if(micMuted || endRequested) java.util.Arrays.fill(frame,12,972,0.toByte())
          sendFrame(frame);frames++
          for(i in 12 until 972 step 2) {
            val v=((frame[i].toInt() and 255) or (frame[i+1].toInt() shl 8)).toShort().toDouble()
            energy+=v*v;samples++
          }
          val now=android.os.SystemClock.elapsedRealtime()
          if(now-reportAt>=2000) {
            android.util.Log.i("DanAtomRelay","capture frames=$frames rms=${kotlin.math.sqrt(energy/maxOf(1L,samples)).toInt()} inputType=${capture.routedDevice?.type} dropped=$dropped")
            frames=0;energy=0.0;samples=0;reportAt=now
          }
        }
      } catch(e:Exception) {
        if(running.get() && generation.get()==epoch && record===capture && route=="headset") fail("headset_capture_failed",epoch)
      }
    },"DanHeadsetCapture").start()
  }
  private fun bluetooth():AudioDeviceInfo? = manager?.availableCommunicationDevices?.firstOrNull {
    it.type==AudioDeviceInfo.TYPE_BLUETOOTH_SCO || it.type==AudioDeviceInfo.TYPE_BLE_HEADSET
  }
  private fun refreshRoute() {
    if(!running.get()) return
    synchronized(lock) {
      val device=bluetooth();headset=device!=null
      if(device==null && !phoneCall && paused) {paused=false;releaseAudio()}
      val desired=if(device!=null && requested && !paused) "headset" else "atom"
      if(desired==route) return
      releaseAudio();route="atom"
      if(desired=="headset") {
        try {
          val audio=manager!!
          val attrs=AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
          // The user explicitly wants media and Dan together. Request ducking,
          // not a pause of the media app, and retain microphone capture when
          // the user subsequently gives a media player permanent focus.
          focus=AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK).setAudioAttributes(attrs)
            .setAcceptsDelayedFocusGain(true).setWillPauseWhenDucked(false)
            .setOnAudioFocusChangeListener { change ->
              if(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT || manager?.mode==AudioManager.MODE_IN_CALL) {
                android.util.Log.i("DanAtomRelay","audio paused: focus=$change")
                paused=true;synchronized(lock) {releaseAudio(true);route="atom"}
              }
              else if(change==AudioManager.AUDIOFOCUS_LOSS || change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) {
                synchronized(lock) {sharingMedia=true;playback?.setVolume(0.7f)}
                android.util.Log.i("DanAtomRelay","media sharing: microphone retained")
              }
              else if(change==AudioManager.AUDIOFOCUS_GAIN && !phoneCall) {
                sharingMedia=false;paused=false;refreshRoute();synchronized(lock){playback?.setVolume(1f)}
              }
            }.build()
          if(audio.requestAudioFocus(focus!!)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED) { paused=true;return }
          takingAudio=true;audio.mode=AudioManager.MODE_IN_COMMUNICATION;ownsCommunication=true
          check(audio.setCommunicationDevice(device!!))
          val format=AudioFormat.Builder().setSampleRate(48000).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
          record=AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_COMMUNICATION)
            .setAudioFormat(format.setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
            .setBufferSizeInBytes(maxOf(9600,AudioRecord.getMinBufferSize(48000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT))).build()
          playback=AudioTrack.Builder().setAudioAttributes(attrs)
            .setAudioFormat(format.setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setBufferSizeInBytes(maxOf(9600,AudioTrack.getMinBufferSize(48000,AudioFormat.CHANNEL_OUT_MONO,AudioFormat.ENCODING_PCM_16BIT)))
            .setTransferMode(AudioTrack.MODE_STREAM).build()
          record!!.startRecording();playback!!.play();route="headset"
          captureHeadset(record!!)
        } catch(e:Exception) {releaseAudio();state="headset_error"}
        finally {takingAudio=false}
      }
    }
  }
  private fun releaseAudio(keepFocus:Boolean=false) {
    sharingMedia=false
    val oldRecord=record;record=null
    try {oldRecord?.stop()}catch(e:Exception){};oldRecord?.release()
    try {playback?.stop()}catch(e:Exception){};playback?.release();playback=null
    if(!keepFocus && focus!=null) {manager?.abandonAudioFocusRequest(focus!!);focus=null}
    if(ownsCommunication) {
      manager?.clearCommunicationDevice()
      if(!phoneCall && manager?.mode==AudioManager.MODE_IN_COMMUNICATION)manager?.mode=AudioManager.MODE_NORMAL
      ownsCommunication=false
    }
  }
  private fun fail(reason:String,epoch:Int) {
    if(generation.get()!=epoch) return
    android.util.Log.w("DanAtomRelay", "relay stopped: $reason; frames=$received; route=$route")
    stop();state=reason
    if(DanAudioLease.owns(audioLease)) context?.stopService(android.content.Intent(context,DanVoiceCallService::class.java))
  }
  fun stop() {
    if(!running.getAndSet(false)) return
    generation.incrementAndGet()
    websocket?.cancel();websocket=null
    try {socket?.close()}catch(e:Exception){};socket=null
    callback?.let {manager?.unregisterAudioDeviceCallback(it)};callback=null
    modeListener?.let {manager?.removeOnModeChangedListener(it)};modeListener=null
    synchronized(lock) {releaseAudio();route="atom";requested=false;paused=false;phoneCall=false;callConnected=false;endRequested=false;micMuted=false;callStartedAt=0L}
    client?.dispatcher?.executorService?.shutdown();client=null;state="off"
  }
}
