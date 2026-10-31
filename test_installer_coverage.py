import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

class InstallerCoverageTests(unittest.TestCase):
    def test_all_top_level_runtime_python_is_packaged(self):
        text = (ROOT / 'installer' / 'AudioMemory.iss').read_text(encoding='utf-8-sig')
        included = set(re.findall(r'Source: "\.\.\\([^"\\]+\.py)"', text))
        runtime = {p.name for p in ROOT.glob('*.py')
                   if not p.name.startswith('test_') and p.name != 'release_check.py'}
        self.assertFalse(runtime - included, 'Installer omits: ' + ', '.join(sorted(runtime - included)))

if __name__ == '__main__':
    unittest.main()
