"""Apply the exact implementation edited on /prompts to a clean, separate trial worktree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def apply_draft(draft: Path, worktree: Path, folder: Path):
    worktree = worktree.resolve()
    draft = draft.resolve(strict=True)
    if draft.parent != folder.resolve() or draft.suffix != '.json':
        raise ValueError('構成図から保存した控えを指定してください。')
    data = draft.read_bytes()
    if hashlib.sha256(data).hexdigest() != draft.stem:
        raise ValueError('保存された変更と内容が違います。')
    item = json.loads(data)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(worktree), *args], text=True).strip()
    if not (worktree / '.git').is_file() or git('rev-parse', '--show-toplevel') != str(worktree) or not git('branch', '--show-current').startswith('dan/'):
        raise ValueError('専用の作業場所を指定してください。')
    catalog = json.loads((worktree / 'frontend/src/components/prompts/program-sources.json').read_text())
    relative = item['path']
    target = (worktree / relative).resolve(strict=True)
    if not target.is_relative_to(worktree) or not any(relative in paths for paths in catalog.values()):
        raise ValueError('構成図に載っている実装を指定してください。')
    if not git('ls-files', '--', relative) or git('status', '--porcelain', '--', relative):
        raise ValueError('この実装に保存前の変更があります。別の作業場所で試してください。')
    original = target.read_text(encoding='utf-8')
    if hashlib.sha256(original.encode()).hexdigest() != item['base_sha']:
        raise ValueError('元の実装が変わりました。')
    mode = target.stat().st_mode
    with tempfile.NamedTemporaryFile(dir=target.parent, mode='w', encoding='utf-8', delete=False) as tmp:
        try:
            tmp.write(item['text'])
            tmp.flush()
            os.chmod(tmp.name, mode)
            os.replace(tmp.name, target)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('draft', type=Path)
    args = parser.parse_args()
    root = Path(os.environ.get('DAN_PROMPTS_DIR') or Path.home() / '.dan/workspace/prompts')
    apply_draft(args.draft, Path.cwd(), root / '.program-trials')
