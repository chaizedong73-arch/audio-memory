import tempfile
import unittest
from pathlib import Path

from release_check import scan


class ReleaseCheckTests(unittest.TestCase):
    def test_scans_desktop_sources_and_skips_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private_path = '\\'.join(('C:', 'Users', 'example', 'notes'))
            for name in ('main.cjs', 'view.tsx'):
                (root / name).write_text(private_path, encoding='utf-8')
            dependency = root / 'node_modules'
            dependency.mkdir()
            (dependency / 'external.js').write_text(private_path, encoding='utf-8')
            self.assertEqual({item[0] for item in scan(root)}, {'main.cjs', 'view.tsx'})

    def test_finds_plain_and_code_escaped_user_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.cs'
            plain = '\\'.join(('C:', 'Users', 'example', 'notes'))
            path.write_text(plain + '\n' + plain.replace('\\', '\\\\') + '\n', encoding='utf-8')
            found = scan(Path(folder))
            self.assertEqual([item[1] for item in found], [1, 2])


if __name__ == '__main__':
    unittest.main()
