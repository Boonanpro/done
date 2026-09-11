"""Qwen on the user's cloud GPU, reached only through an authenticated SSH channel."""
import http.client
import json
import time
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'uploads/tts-service/cloud.json'
REMOTE = '/workspace/dan-tts'


def settings():
    if not CONFIG.exists():
        return None
    value = json.loads(CONFIG.read_text(encoding='utf-8'))
    return value if value.get('enabled') else None


def connect(config):
    import paramiko
    client = paramiko.SSHClient()
    known = CONFIG.parent / 'cloud_known_hosts'
    known.parent.mkdir(parents=True, exist_ok=True)
    known.touch(exist_ok=True)
    client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(config['host'], port=int(config['port']), username='root',
                   key_filename=config['key_file'], timeout=15, auth_timeout=15,
                   look_for_keys=False, allow_agent=False)
    return client


def request(ssh, config, method, path, payload=None, timeout=600):
    channel = ssh.get_transport().open_channel('direct-tcpip',
        ('127.0.0.1', int(config.get('service_port', 9019))), ('127.0.0.1', 0), timeout=15)
    channel.settimeout(timeout)
    connection = http.client.HTTPConnection('127.0.0.1', timeout=timeout)
    connection.sock = channel
    try:
        connection.request(method, path, body=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization':'Bearer '+config['token'], 'Content-Type':'application/json'})
        response = connection.getresponse()
        result = json.loads(response.read())
        if response.status >= 400:
            raise RuntimeError(result.get('error') or f'Cloud voice HTTP {response.status}')
        return result
    finally:
        connection.close()


def synthesize(config, profile, lines, out_dir, timeout=600):
    """Upload the selected voice and return WAVs in the same contract as local TTS."""
    from app.services.qwen_policy import require_enabled
    require_enabled()
    started = time.monotonic()
    ssh = connect(config)
    try:
        try:
            health = request(ssh, config, 'GET', '/health', timeout=10)
        except Exception:
            # After a GPU container restart, start the already provisioned service.
            # This never starts/rents a GPU or installs software.
            _, stdout, _ = ssh.exec_command(
                'cd /workspace/dan-tts && HF_HOME=/workspace/dan-tts/models venv/bin/python -m app.services.tts_worker launch', timeout=15)
            if stdout.channel.recv_exit_status() != 0:
                raise RuntimeError('Could not start the installed cloud voice service')
            for attempt in range(10):
                try:
                    health = request(ssh, config, 'GET', '/health', timeout=5)
                    break
                except Exception:
                    if attempt == 9:raise
                    time.sleep(.5)
        if health.get('service') != 'dan-tts':
            raise RuntimeError('Cloud voice service is not ready')
        with ssh.open_sftp() as sftp:
            data = json.loads((profile/'profile.json').read_text(encoding='utf-8'))
            import hashlib
            ref = profile/(data.get('ref_audio') or 'ref.wav')
            identity = hashlib.sha256((profile/'profile.json').read_bytes()+ref.read_bytes()).hexdigest()
            folder = REMOTE+'/uploads/voice/'+identity
            try:
                sftp.stat(folder+'/profile.json')
            except FileNotFoundError:
                sftp.mkdir(folder)
                sftp.put(str(ref), folder+'/ref.wav')
                data['ref_audio'] = 'ref.wav'
                with sftp.open(folder+'/profile.json', 'w') as f:
                    f.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
            output = REMOTE+'/uploads/requests/'+uuid.uuid4().hex
            sftp.mkdir(output)
            # Remote filenames are generated here, never taken from spoken text.
            names = {f'line_{i}':name for i,name in enumerate(lines)}
            result = request(ssh, config, 'POST', '/synthesize', {
                'profile':folder, 'out_dir':output,
                'lines':{key:lines[name] for key,name in names.items()}}, timeout=timeout)
            if not result.get('ok'):
                return result
            files = {}
            for key, name in names.items():
                row = result['files'][key]
                expected = output+'/'+key+'.wav'
                if str(PurePosixPath(row['path'])) != expected:
                    raise ValueError('Unexpected cloud voice output path')
                dest = out_dir/(name+'.wav')
                sftp.get(expected, str(dest))
                files[name] = {**row, 'path':str(dest)}
            return {**result, 'files':files, 'backend':'cloud', 'pod_id':config.get('pod_id'),
                    'transfer_included_seconds':round(time.monotonic()-started, 2)}
    finally:
        ssh.close()
