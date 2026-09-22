"""Privacy and stale-command regressions without hardware or paid sessions."""
import unittest
from unittest.mock import patch
from voice_state import HEADER, VoiceGate


class VoiceGateTests(unittest.TestCase):
    def test_cold_boot_and_ready_lease(self):
        gate = VoiceGate()
        gate.receive(HEADER.pack(0, 123, 0))
        gate.lease(123, 0, True)
        self.assertFalse(gate.ready)
        gate.receive(HEADER.pack(1, 123, 1))
        self.assertFalse(gate.ready)
        with patch('voice_state.time.monotonic', return_value=10):
            self.assertTrue(gate.lease(123, 1, True))
            self.assertTrue(gate.ready)
        with patch('voice_state.time.monotonic', return_value=12.1):
            self.assertFalse(gate.ready)

    def test_off_and_reconnect_do_not_resurrect_session(self):
        gate = VoiceGate()
        gate.receive(HEADER.pack(1, 123, 1))
        gate.lease(123, 1, True)
        gate.control(False)
        self.assertFalse(gate.ready)
        self.assertFalse(gate.wanted)
        self.assertEqual(HEADER.unpack(gate.outgoing()), (2, 123, 1))
        gate.disconnected()
        gate.receive(HEADER.pack(1, 123, 1))
        self.assertFalse(gate.wanted)  # Unacknowledged OFF survives TCP loss.
        gate.receive(HEADER.pack(0, 123, 2))
        self.assertFalse(gate.wanted)
        self.assertIsNone(gate.pending)
        self.assertFalse(gate.lease(123, 1, True))
        gate.disconnected()
        gate.receive(HEADER.pack(0, 123, 2))
        self.assertFalse(gate.ready)

    def test_old_host_command_cannot_override_new_button_intent(self):
        gate = VoiceGate()
        gate.receive(HEADER.pack(0, 123, 0))
        gate.control(True)
        self.assertEqual(HEADER.unpack(gate.outgoing()), (4, 123, 0))
        gate.receive(HEADER.pack(0, 123, 2))  # User pressed ON then OFF.
        self.assertIsNone(gate.pending)
        self.assertFalse(gate.wanted)
        self.assertFalse(gate.lease(123, 1, True))

    def test_active_reconnect_requires_new_lease_and_reboot_defaults_off(self):
        gate = VoiceGate()
        gate.receive(HEADER.pack(1, 123, 1))
        gate.lease(123, 1, True)
        gate.disconnected()
        gate.receive(HEADER.pack(1, 123, 1))
        self.assertTrue(gate.wanted)
        self.assertFalse(gate.ready)
        gate.lease(123, 1, True)
        self.assertTrue(gate.ready)
        gate.receive(HEADER.pack(0, 456, 0))
        self.assertFalse(gate.ready)
        self.assertFalse(gate.lease(123, 1, True))


if __name__ == '__main__': unittest.main()
