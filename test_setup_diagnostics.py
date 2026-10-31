import unittest
from unittest.mock import patch

import setup


class SetupDiagnosticsTests(unittest.TestCase):
    def test_missing_microphone_is_reported_without_install_failure(self):
        with patch.object(setup.importlib.util, 'find_spec', return_value=object()), \
             patch('sounddevice.query_devices', return_value=[]):
            self.assertEqual(setup.doctor(), 0)

    def test_missing_dependency_fails(self):
        with patch.object(setup.importlib.util, 'find_spec', return_value=None):
            self.assertEqual(setup.doctor(), 1)


if __name__ == '__main__':
    unittest.main()
