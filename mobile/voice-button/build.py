"""Build the permission-free side-button launcher using the installed Android SDK.

Usage: python build.py --keystore <Done debug.keystore> --out <output.apk>
Uses the existing Android development signing key (androiddebugkey).
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

p = argparse.ArgumentParser()
p.add_argument('--keystore', required=True, type=Path)
p.add_argument('--out', required=True, type=Path)
a = p.parse_args()
source = Path(__file__).resolve().parent
sdk = Path(os.environ.get('ANDROID_HOME', '/opt/homebrew/share/android-commandlinetools'))
java = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'))
bt = sdk / 'build-tools/36.0.0'
jar = sdk / 'platforms/android-35/android.jar'
env = dict(os.environ, JAVA_HOME=str(java))
def run(*cmd):
    subprocess.run(list(map(str, cmd)), check=True, env=env)
a.out = a.out.resolve()
a.out.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='dan-voice-button-') as tmp:
    t = Path(tmp)
    classes = t / 'classes'
    classes.mkdir()
    run(java/'bin/javac', '-source', '8', '-target', '8', '-classpath', jar,
        '-d', classes, source/'VoiceButtonActivity.java')
    run(bt/'d8', '--lib', jar, '--min-api', '26', '--output', t, *classes.rglob('*.class'))
    run(bt/'aapt', 'package', '-f', '-M', source/'AndroidManifest.xml', '-I', jar, '-F', t/'raw.apk')
    with zipfile.ZipFile(t/'raw.apk', 'a', zipfile.ZIP_DEFLATED) as z:
        z.write(t/'classes.dex', 'classes.dex')
    run(bt/'zipalign', '-f', '4', t/'raw.apk', t/'aligned.apk')
    run(bt/'apksigner', 'sign', '--ks', a.keystore.resolve(), '--ks-key-alias', 'androiddebugkey',
        '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--out', a.out, t/'aligned.apk')
    run(bt/'apksigner', 'verify', a.out)
print(a.out)
