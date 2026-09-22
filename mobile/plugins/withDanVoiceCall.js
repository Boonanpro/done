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
      'android.permission.WAKE_LOCK', 'android.permission.POST_NOTIFICATIONS',
      'android.permission.POST_PROMOTED_NOTIFICATIONS',
    ]);
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(mod.modResults);
    app.service = app.service || [];
    if (!app.service.some(s => s.$['android:name'] === 'app.done.dan.voice.DanVoiceCallService')) {
      app.service.push({$: {'android:name': 'app.done.dan.voice.DanVoiceCallService', 'android:exported': 'false',
        'android:foregroundServiceType': 'microphone', 'android:stopWithTask': 'false'}});
    }
    return mod;
  });
  config = withMainApplication(config, mod => {
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
    const dest = path.join(root, 'android/app/src/main/java/app/done/dan/voice');
    fs.mkdirSync(dest, {recursive: true});
    for (const file of ['DanVoiceCallModule.kt','DanVoiceCallService.kt','DanAtomRelay.kt','DanPcmQueue.java','DanExternalAudio.java','DanWebRtcAudio.kt','DanAtomSocket.java','DanAudioLease.java']) fs.copyFileSync(path.join(root,'native/voice',file),path.join(dest,file));
    const rtcDest = path.join(root, 'android/app/src/main/java/com/oney/WebRTCModule');
    fs.mkdirSync(rtcDest, {recursive: true});
    fs.copyFileSync(path.join(root,'native/voice/DanWebRtcAccess.java'),path.join(rtcDest,'DanWebRtcAccess.java'));
    const raw = path.join(root,'android/app/src/main/res/raw'); fs.mkdirSync(raw,{recursive:true});
    for (const cue of ['ready','standby']) fs.copyFileSync(path.join(root,`native/voice/audio/Dan-${cue}-two-note.wav`),path.join(raw,`dan_${cue}.wav`));
    fs.copyFileSync(path.join(root,'native/voice/audio/Dan-waiting.wav'),path.join(raw,'dan_waiting.wav'));
    return mod;
  }]);
};
