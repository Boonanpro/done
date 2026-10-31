"""A bounded, room-private stream of the exact Android device being operated.

The capture worker owns only its adb/ffmpeg children. It exits after the host dies
or the viewer lease expires; it never kills other adb sessions or phone processes.
"""
import os
import selectors
import shutil
import subprocess
import sys
import time
import uuid
from .voice_screen_stream import MAX_FRAME, frame_path, write_frame, url

_stream = None


async def follow(serial):
    global _stream
    room = os.environ.get('DAN_SESSION_ID')
    if not room or os.environ.get('DAN_TOOL_HOST') != '1':
        return ''
    if _stream and (_stream['serial'] != serial or _stream['process'].poll() is not None):
        if _stream['process'].poll() is None:
            _stream['process'].terminate()
        _stream = None
    if not _stream:
        if not shutil.which('ffmpeg'):
            return ''
        key = uuid.uuid4().hex
        process = subprocess.Popen([sys.executable, '-m', __name__, room, serial, key, str(os.getpid())],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _stream = {'serial':serial, 'key':key, 'process':process}
    # Capture startup runs alongside the operation. A slow/unsupported encoder
    # falls back to a still; never repeat an operation to obtain a picture.
    path = frame_path(room, _stream['key'])
    return url(room,_stream['key']) if path.exists() else ''


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=2)


def capture(room, serial, key, parent):
    from .phone_control import ADB
    path = frame_path(room,key)
    lease = path.with_suffix('.watch')
    started = time.time()
    adb = decoder = None
    import signal
    def end(*_): raise SystemExit()
    signal.signal(signal.SIGTERM,end)
    try:
        while True:
            recording_started = time.time()
            adb = subprocess.Popen([ADB,'-s',serial,'exec-out','screenrecord','--output-format=h264',
                                    '--bit-rate','2000000','--size','720x1280','--time-limit','180','-'],
                                   stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            decoder = subprocess.Popen([shutil.which('ffmpeg'),'-loglevel','error','-probesize','32',
                '-analyzeduration','0','-threads','1','-flags','low_delay','-f','h264','-i','pipe:0','-fps_mode','passthrough','-f','image2pipe',
                '-vcodec','mjpeg','-q:v','5','pipe:1'],stdin=adb.stdout,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            adb.stdout.close()
            # H.264 parsers may need the next frame boundary on a static screen.
            # Seed with an actual screenshot, then replace it with decoded frames.
            latest = None
            try:
                shot = subprocess.run([ADB,'-s',serial,'exec-out','screencap','-p'],capture_output=True,timeout=5)
                if shot.returncode == 0 and len(shot.stdout) <= 12_000_000:
                    jpeg = subprocess.run([shutil.which('ffmpeg'),'-loglevel','error','-i','pipe:0',
                        '-frames:v','1','-vf','scale=720:-2','-f','image2pipe','-vcodec','mjpeg','pipe:1'],
                        input=shot.stdout,capture_output=True,timeout=5)
                    if jpeg.returncode == 0:
                        latest=jpeg.stdout;write_frame(room,key,latest)
            except (OSError,subprocess.TimeoutExpired):
                pass
            refreshed=time.monotonic()
            buffer=b''; last_frame=0.0
            with selectors.DefaultSelector() as selector:
                selector.register(decoder.stdout,selectors.EVENT_READ)
                while True:
                    try: os.kill(parent,0)
                    except ProcessLookupError: return
                    try: last_view = lease.stat().st_mtime
                    except FileNotFoundError: last_view = started
                    if time.time()-last_view > 30: return
                    if latest and time.monotonic()-refreshed >= 5:
                        write_frame(room,key,latest);refreshed=time.monotonic()
                    if not selector.select(timeout=.5):
                        if decoder.poll() is not None: break
                        continue
                    chunk=os.read(decoder.stdout.fileno(),65536)
                    if not chunk: break
                    buffer+=chunk
                    if len(buffer)>MAX_FRAME: return
                    while True:
                        end_at=buffer.find(b'\xff\xd9')
                        if end_at<0: break
                        jpeg,buffer=buffer[:end_at+2],buffer[end_at+2:]
                        now=time.monotonic()
                        if jpeg.startswith(b'\xff\xd8') and now-last_frame >= 1/20:
                            write_frame(room,key,jpeg);latest=jpeg;last_frame=now;refreshed=now
            stop(decoder);stop(adb)
            # Restart only the documented recording time limit, not failures.
            if time.time()-recording_started < 175: return
    finally:
        stop(decoder);stop(adb)
        path.unlink(missing_ok=True);lease.unlink(missing_ok=True)


if __name__ == '__main__':
    capture(sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4]))
