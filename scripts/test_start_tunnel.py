"""Legacy tunnel recovery must never terminate unrelated or named connectors."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('start_tunnel', Path(__file__).with_name('start_tunnel.py'))
tunnels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tunnels)


class TunnelRecoveryTests(unittest.TestCase):
    def test_only_owned_quick_tunnels_are_stopped(self):
        arguments = [
            ['cloudflared', 'tunnel', '--url', 'http://127.0.0.1:9000'],
            ['cloudflared', 'tunnel', '--url', 'http://127.0.0.1:8000'],
            ['cloudflared', 'tunnel', 'run', '--token-file', 'dan-paina.token'],
            ['cloudflared', 'tunnel', '--url', 'http://127.0.0.1:7777'],
            ['cloudflared', 'tunnel', '--url'],
        ]
        processes = [Mock(info={'name':'cloudflared.exe', 'cmdline':args}) for args in arguments]
        with patch.object(tunnels.psutil, 'process_iter', return_value=processes):
            tunnels.kill_existing_tunnels()
        for process in processes[:2]:
            process.kill.assert_called_once()
        for process in processes[2:]:
            process.kill.assert_not_called()

    def test_exiting_process_does_not_prevent_other_recovery(self):
        stale = Mock(info={'name':'cloudflared.exe','cmdline':['cloudflared','--url','http://127.0.0.1:9000']})
        stale.kill.side_effect = tunnels.psutil.NoSuchProcess(123)
        live = Mock(info={'name':'cloudflared.exe','cmdline':['cloudflared','--url','http://127.0.0.1:8000']})
        with patch.object(tunnels.psutil,'process_iter',return_value=[stale,live]):
            tunnels.kill_existing_tunnels()
        live.kill.assert_called_once()


if __name__ == '__main__':
    unittest.main()
