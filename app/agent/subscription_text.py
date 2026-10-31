"""Text-only CLI generation with bounded subscription-provider failover."""
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


class UsageLimitError(RuntimeError):
    pass


def codex_text(prompt, model, timeout, cwd=None):
    from app.agent.codex_runner import resolve_codex_cli
    from app.agent import provider_failover
    executable = resolve_codex_cli()
    if not executable:
        return None
    source = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    # A private config keeps project instructions, MCP servers and tools out of
    # article/title generation. Copy the existing sign-in; never use an API key.
    with tempfile.TemporaryDirectory(prefix='dan-text-') as directory:
        home = Path(directory)
        auth = source / 'auth.json'
        if not auth.exists():
            return None
        shutil.copyfile(auth, home / 'auth.json')
        os.chmod(home / 'auth.json', 0o600)
        (home / 'config.toml').write_text('forced_login_method = "chatgpt"\nweb_search = "disabled"\n[features]\nshell_tool = false\n', encoding='utf-8')
        result_file = home / 'answer.txt'
        env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'CLAUDECODE')}
        env['CODEX_HOME'] = str(home)
        result = subprocess.run([executable, 'exec', '--ephemeral', '--json',
            '--skip-git-repo-check', '--sandbox', 'read-only', '-m', model,
            '--output-last-message', str(result_file), '-'], input=prompt,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            env=env, cwd=cwd or directory, timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        answer = result_file.read_text(encoding='utf-8').strip() if result_file.exists() else ''
        # Parse errors rather than classifying an ordinary answer about limits.
        errors = []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') in ('error', 'turn.failed'):
                errors.append(json.dumps(event))
        error = '\n'.join(errors) or (result.stderr if result.returncode else '')
        if provider_failover.exhausted({'type': 'error', 'text': error}) or provider_failover.exhausted({'text': answer}):
            raise UsageLimitError(error or answer)
        return answer if result.returncode == 0 else None


def generate(prompt, model, timeout, cwd, claude_text):
    from app.agent import provider_failover as pf, codex_runner, model_catalog
    model = pf.preferred(model_catalog.current(model))
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        backend = codex_runner.backend_for_model(model)
        if not pf.available(backend):
            return None
        try:
            run = codex_text if backend == 'codex' else claude_text
            return run(prompt, model=model, timeout=max(1, deadline-time.monotonic()), cwd=cwd)
        except UsageLimitError:
            pf.mark_exhausted(backend)
            other = 'claude' if backend == 'codex' else 'codex'
            if attempt or not pf.available(other) or time.monotonic() >= deadline:
                return None
            model = pf.alternative(backend)
            logging.getLogger(__name__).warning('Usage limit on %s; continuing text generation with %s', backend, model)
        except (subprocess.TimeoutExpired, OSError):
            return None
    return None
