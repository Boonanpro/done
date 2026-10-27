import os, subprocess, time, sys
sys_path = __import__("sys").path; sys_path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
os.environ.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
from app.core.generations import core_env
assert core_env().get('CLAUDE_CODE_OAUTH_TOKEN')
from app.services import parallel_job_runner as r
p = subprocess.Popen(['/bin/sh', '-c', 'sleep 100 & sleep 100']); time.sleep(.3)
r._procs['t'] = p; r._kill('t'); time.sleep(.3)
assert p.poll() is not None
print('ok')
