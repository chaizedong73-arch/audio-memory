"""Read-only publishing preflight: report paths and line numbers, never secret values."""
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent
SKIP={'.venv','venv','out','record','models','__pycache__','.git','config','node_modules','dist','build','.gradle','test-artifacts'}
SUFFIX={'.py','.ps1','.cs','.xaml','.md','.json','.html','.js','.cjs','.mjs','.ts','.tsx','.jsx','.cmd','.sh','.txt'}
RULES={
    'personal Windows path':re.compile(r'(?i)(?:[A-Z]:[\\/]+)Users[\\/]+(?!<|\{|%)[^\\/\s"\']+'),
    'private key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'known API token':re.compile(r'(?:KGAT_|ghp_|github_pat_)[A-Za-z0-9_]{12,}'),
}

def scan(root=ROOT):
    findings=[]
    for path in Path(root).rglob('*'):
        if not path.is_file() or any(part in SKIP for part in path.relative_to(root).parts) or path.suffix.lower() not in SUFFIX:continue
        if path.name=='release_check.py':continue
        try: lines=path.read_text(encoding='utf-8-sig').splitlines()
        except (UnicodeError,OSError):findings.append((str(path.relative_to(root)),0,'unreadable text'));continue
        for n,line in enumerate(lines,1):
            for name,pattern in RULES.items():
                if pattern.search(line):findings.append((str(path.relative_to(root)),n,name))
    return findings

if __name__=='__main__':
    findings=scan()
    for path,n,reason in findings:print(f'{path}:{n}: {reason}')
    print(f'Found {len(findings)} items. This scan is incomplete and does not prove files safe to publish.')
    sys.exit(1 if findings else 0)
