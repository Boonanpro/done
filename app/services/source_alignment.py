"""Locate matching recorded speech across edited/original media without an AI guess."""
import subprocess
import numpy as np
from scipy.signal import correlate
from app.services.timeline_captions import _ffmpeg
from app.services.editor_workflows import playback_audio_path
from app.services.timeline_live import _assets


def pcm(path):
    result=subprocess.run([_ffmpeg(),'-nostdin','-v','error','-i',str(path),'-vn','-ac','1','-ar','8000','-f','f32le','-'],
        capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError(result.stderr.decode('utf-8',errors='replace')[-500:])
    return np.frombuffer(result.stdout,dtype='<f4').astype(np.float64)


def match_samples(reference,candidate,at,window=2.0,rate=8000):
    sample=reference[round(at*rate):round((at+window)*rate)]
    if len(sample)<rate//20 or len(candidate)<len(sample):raise ValueError('Audio range too short')
    sample=sample-sample.mean()
    energy=np.dot(sample,sample)
    if energy<1e-8:return {'reference_time':at,'match':None,'reason':'silence'}
    n=len(sample)
    sums=np.concatenate(([0.],np.cumsum(candidate)))
    squares=np.concatenate(([0.],np.cumsum(candidate*candidate)))
    local_energy=np.maximum(squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n,0)
    scores=correlate(candidate,sample,mode='valid',method='fft')/np.sqrt(np.maximum(local_energy*energy,1e-16))
    best=int(np.argmax(scores))
    return {'reference_time':at,'candidate_time':best/rate,'offset':best/rate-at,'correlation':float(scores[best]),'window':len(sample)/rate}


def locate(room,reference_asset_id,candidate_asset_id,times,window=2.0):
    assets=_assets(room)
    if not 1<=len(times)<=30 or not .5<=window<=10:raise ValueError('Use 1–30 locations and 0.5–10 second samples')
    paths=[playback_audio_path(room,assets[i]) for i in (reference_asset_id,candidate_asset_id)]
    reference,candidate=[pcm(p) for p in paths]
    if any(t<0 or (t+window)*8000>len(reference) for t in times):raise ValueError('Sample is outside reference audio')
    return {'ok':True,'reference_asset_id':reference_asset_id,'candidate_asset_id':candidate_asset_id,
            'matches':[match_samples(reference,candidate,t,window) for t in times],
            'note':'Measured audio correlation, not a visual match. Low scores or changing offsets require inspection; no edit was made.'}
