"""no-op placeholder hook"""
import sys
try:
    sys.stdin.read()
except Exception:
    pass
sys.exit(0)
