import tempfile
import unittest
from pathlib import Path

from release_check import scan


class ReleaseCheckTests(unittest.TestCase):
    def test_finds_plain_and_code_escaped_user_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.cs'
            plain = '\\'.join(('C:', 'Users', 'example', 'notes'))
            path.write_text(plain + '\n' + plain.replace('\\', '\\\\') + '\n', encoding='utf-8')
            found = scan(Path(folder))
            self.assertEqual([item[1] for item in found], [1, 2])


if __name__ == '__main__':
    unittest.main()
