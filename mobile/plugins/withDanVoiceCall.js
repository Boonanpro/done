const { AndroidConfig, withAndroidManifest, withMainApplication, withProjectBuildGradle, withAppBuildGradle, withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');
module.exports = function withDanVoiceCall(config) {
  config = withAppBuildGradle(config, mod => {
    if (!mod.modResults.contents.includes('// Dan OTA runtime consistency')) {
      mod.modResults.contents += `
// Dan OTA runtime consistency: an APK version bump must not retain old update targeting.
tasks.register('verifyDanOtaRuntime') {
  doLast {
    def expoConfig = new groovy.json.JsonSlurper().parse(file('../../app.json')).expo
    def resources = file('src/main/res/values/strings.xml').text
    def runtime = (resources =~ /<string name="expo_runtime_version">([^<]+)<\\/string>/)
    if (!runtime.find() || runtime.group(1) != expoConfig.version || android.defaultConfig.versionName != expoConfig.version) {
      throw new GradleException('APK version and Expo runtime differ. Run npx expo prebuild --platform android before building.')
    }
  }
}
tasks.named('preBuild').configure { dependsOn('verifyDanOtaRuntime') }
`;
    }
    if (!mod.modResults.contents.includes('// Dan pin Opus decoder')) {
      mod.modResults.contents += `
// Dan pin Opus decoder: the pin (Omi firmware) sends 10 ms Opus frames over BLE.
dependencies { implementation 'io.github.jaredmdobson:concentus:1.0.2' }
`;
    }
    if (!mod.modResults.contents.includes('// Dan pin wake word')) {
      mod.modResults.contents += `
// Dan pin wake word: openWakeWord models run on the phone.
dependencies { implementation 'com.microsoft.onnxruntime:onnxruntime-android:1.20.0' }
`;
    }
    return mod;
  });
  config = withProjectBuildGradle(config, mod => {
    if (!mod.modResults.contents.includes('// Dan external audio WebRTC')) {
      mod.modResults.contents += `
// Dan external audio WebRTC: one implementation, pinned for mutable PCM input and track sinks.
allprojects {
  configurations.configureEach {
    resolutionStrategy.dependencySubstitution {
      substitute module('org.jitsi:webrtc') using module('io.github.webrtc-sdk:android:144.7559.14')
    }
  }
}
`;
    }
    return mod;
  });
  config = withAndroidManifest(config, mod => {
    AndroidConfig.Permissions.ensurePermissions(mod.modResults, [
      'android.permission.FOREGROUND_SERVICE', 'android.permission.FOREGROUND_SERVICE_MICROPHONE',
      'android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE',
      'android.permission.WAKE_LOCK', 'android.permission.POST_NOTIFICATIONS',
      'android.permission.POST_PROMOTED_NOTIFICATIONS', 'android.permission.BLUETOOTH_SCAN',
      // The pin as a companion device: Android revives the app when the pin appears and lets it start from the background.
      'android.permission.REQUEST_OBSERVE_COMPANION_DEVICE_PRESENCE', 'android.permission.REQUEST_COMPANION_RUN_IN_BACKGROUND',
      'android.permission.REQUEST_COMPANION_USE_DATA_IN_BACKGROUND',
      'android.permission.REQUEST_COMPANION_START_FOREGROUND_SERVICES_FROM_BACKGROUND',
      // 「録音を再開」 after the phone was switched on (DanLifelogResume).
      'android.permission.RECEIVE_BOOT_COMPLETED',
    ]);
    const features = mod.modResults.manifest['uses-feature'] = mod.modResults.manifest['uses-feature'] || [];
    if (!features.some(f => f.$['android:name'] === 'android.software.companion_device_setup'))
      features.push({$: {'android:name': 'android.software.companion_device_setup', 'android:required': 'false'}});
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(mod.modResults);
    app.activity = app.activity || [];
    if (!app.activity.some(a => a.$['android:name'] === 'app.done.dan.voice.DanVoiceShortcutActivity')) {
      app.activity.push({$: {'android:name': 'app.done.dan.voice.DanVoiceShortcutActivity',
        'android:exported': 'true', 'android:label': 'ダンと話す', 'android:theme': '@android:style/Theme.NoDisplay',
        'android:excludeFromRecents': 'true'},
        'intent-filter': [{action: [{$: {'android:name': 'android.intent.action.MAIN'}}],
          category: [{$: {'android:name': 'android.intent.category.LAUNCHER'}}]}]});
    }
    // Never reuse MainActivity's task base intent as the shortcut: Android otherwise
    // only brings that task forward on the second launch, skipping this Activity.
    const shortcut = app.activity.find(a => a.$['android:name'] === 'app.done.dan.voice.DanVoiceShortcutActivity');
    shortcut.$['android:taskAffinity'] = '';
    shortcut.$['android:noHistory'] = 'true';
    if (!app.activity.some(a => a.$['android:name'] === 'app.done.dan.voice.DanLifelogResumeActivity')) {
      app.activity.push({$: {'android:name': 'app.done.dan.voice.DanLifelogResumeActivity', 'android:exported': 'false',
        'android:theme': '@android:style/Theme.Translucent.NoTitleBar', 'android:excludeFromRecents': 'true',
        'android:taskAffinity': '', 'android:noHistory': 'true'}});
    }
    app.receiver = app.receiver || [];
    if (!app.receiver.some(r => r.$['android:name'] === 'app.done.dan.voice.DanLifelogResumeReceiver')) {
      app.receiver.push({$: {'android:name': 'app.done.dan.voice.DanLifelogResumeReceiver', 'android:exported': 'true'},
        'intent-filter': [{action: [{$: {'android:name': 'android.intent.action.BOOT_COMPLETED'}},
          {$: {'android:name': 'android.intent.action.MY_PACKAGE_REPLACED'}}]}]});
    }
    app.service = app.service || [];
    const existing = app.service.find(s => s.$['android:name'] === 'app.done.dan.voice.DanVoiceCallService');
    if (existing) existing.$['android:foregroundServiceType'] = 'microphone|connectedDevice'; // prebuild reuses android/
    else {
      app.service.push({$: {'android:name': 'app.done.dan.voice.DanVoiceCallService', 'android:exported': 'false',
        'android:foregroundServiceType': 'microphone|connectedDevice', 'android:stopWithTask': 'false'}});
    }
    if (!app.service.some(s => s.$['android:name'] === 'app.done.dan.voice.DanPinPresenceService')) {
      app.service.push({$: {'android:name': 'app.done.dan.voice.DanPinPresenceService', 'android:exported': 'true',
        'android:permission': 'android.permission.BIND_COMPANION_DEVICE_SERVICE'},
        'intent-filter': [{action: [{$: {'android:name': 'android.companion.CompanionDeviceService'}}]}]});
    }
    return mod;
  });
  config = withMainApplication(config, mod => {
    if (!mod.modResults.contents.includes('app.done.dan.voice.DanVoiceShortcut.install(this)')) {
      mod.modResults.contents = mod.modResults.contents.replace('super.onCreate()',
        'super.onCreate()\n    app.done.dan.voice.DanVoiceShortcut.install(this)');
    }
    if (!mod.modResults.contents.includes('add(app.done.dan.voice.DanVoiceCallPackage())')) {
      mod.modResults.contents = mod.modResults.contents.replace(/PackageList\(this\)\.packages\.apply \{/, '$&\n              add(app.done.dan.voice.DanVoiceCallPackage())');
    }
    if (!mod.modResults.contents.includes('app.done.dan.voice.DanWebRtcAudio.prepare(this)')) {
      mod.modResults.contents = mod.modResults.contents.replace('loadReactNative(this)',
        'app.done.dan.voice.DanWebRtcAudio.prepare(this)\n    loadReactNative(this)');
    }
    return mod;
  });
  return withDangerousMod(config, ['android', async mod => {
    const root = mod.modRequest.projectRoot;
    require('../scripts/patch-incall-focus.cjs').patch(root);
    require('../scripts/patch-webrtc-field-trials.cjs').patch(root);
    require('../scripts/patch-webrtc-audio-processing.cjs').patch(root);
    const dest = path.join(root, 'android/app/src/main/java/app/done/dan/voice');
    fs.mkdirSync(dest, {recursive: true});
    for (const file of ['DanVoiceShortcutActivity.kt','DanVoiceCallModule.kt','DanVoiceCallService.kt','DanPcmQueue.java','DanExternalAudio.java','DanWebRtcAudio.kt','DanAudioLease.java','DanQuietSpeechLift.java','DanQuietSpeechProcessing.java','DanPinBle.java','DanPinSelfTest.kt','DanPinLink.kt','DanPinWake.java','DanPinPresenceService.kt','DanPinLifelog.java','DanPhoneLifelog.java','DanLifelogResume.kt']) fs.copyFileSync(path.join(root,'native/voice',file),path.join(dest,file));
    const rtcDest = path.join(root, 'android/app/src/main/java/com/oney/WebRTCModule');
    fs.mkdirSync(rtcDest, {recursive: true});
    fs.copyFileSync(path.join(root,'native/voice/DanWebRtcAccess.java'),path.join(rtcDest,'DanWebRtcAccess.java'));
    // 「ヘイダン」: openWakeWord feature models + our classifier (trained in D:/dan-hw/kws), copied in when present.
    const wakeSrc = 'D:/dan-hw/kws/android', assets = path.join(root, 'android/app/src/main/assets');
    fs.mkdirSync(assets, {recursive: true});
    for (const f of ['melspectrogram.onnx', 'embedding_model.onnx', 'hey_dan.onnx'])
      if (fs.existsSync(path.join(wakeSrc, f))) fs.copyFileSync(path.join(wakeSrc, f), path.join(assets, f));
    const raw = path.join(root,'android/app/src/main/res/raw'); fs.mkdirSync(raw,{recursive:true});
    for (const cue of ['ready','standby']) fs.copyFileSync(path.join(root,`native/voice/audio/Dan-${cue}-two-note.wav`),path.join(raw,`dan_${cue}.wav`));
    fs.copyFileSync(path.join(root,'native/voice/audio/Dan-waiting.wav'),path.join(raw,'dan_waiting.wav'));
    return mod;
  }]);
};
