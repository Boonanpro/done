"""Provision the current, user-confirmed router profile over USB. Never print its key."""
import sys,subprocess,re,json,secrets,time,argparse,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.tmp/atom-audio-tools'))
p=argparse.ArgumentParser()
p.add_argument('--ssid',required=True)
p.add_argument('--scan',action='store_true')
args=p.parse_args()
import serial
from serial.tools import list_ports

config_path=Path(os.environ.get('DAN_ATOM_CONFIG',str(ROOT/'.tmp/atom-wifi-pairing.json')))
config_path.parent.mkdir(parents=True,exist_ok=True)
cfg=json.loads(config_path.read_text()) if config_path.exists() else {'key':secrets.token_hex(16)}
ports=[p for p in list_ports.comports() if p.vid==0x303a and p.pid==0x8001]
assert len(ports)==1
s=serial.Serial(ports[0].device,115200,timeout=.3);s.dtr=True
if '--scan' in sys.argv:
    s.write(b'Q');time.sleep(4);print(s.read(4096).decode(errors='replace'));s.close();sys.exit()
result=subprocess.run(['netsh','wlan','show','profile','name='+args.ssid,'key=clear'],capture_output=True)
text=result.stdout.decode('cp932',errors='replace')
match=re.search(r'(?:Key Content|主要なコンテンツ)\s*:\s*(.+)',text)
if not match:raise RuntimeError('Saved router profile did not expose a key; no settings changed')
password=match.group(1).strip()
payload=json.dumps({'ssid':args.ssid,'password':password,'key':cfg['key']},ensure_ascii=True,separators=(',',':'))
assert len(payload)<318
s.write(('W'+payload+'\n').encode('ascii'))
del password,payload,text,result,match
time.sleep(.3);print(s.read(2048).decode(errors='replace'))
for _ in range(20):
    s.write(b'N');time.sleep(.3);response=s.read(2048).decode(errors='replace')
    print(response.strip())
    if 'connected=1' in response:
        ip=re.search(r'ip=([\d.]+)',response).group(1)
        cfg['ip']=ip;cfg['ssid']=args.ssid;config_path.write_text(json.dumps(cfg),encoding='utf-8')
        print('Pairing saved (key not displayed), device IP:',ip);break
    time.sleep(1)
else:raise RuntimeError('Router connection not established')
s.close()
