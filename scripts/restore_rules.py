"""Restore RULES.md to pre-cleanup state."""
from pathlib import Path

rules = Path.home() / '.dan' / 'workspace' / 'RULES.md'
restore = Path(__file__).parent / 'rules_backup.txt'
rules.write_text(restore.read_text(encoding='utf-8'), encoding='utf-8')
print(f"Restored: {rules.stat().st_size} bytes")
