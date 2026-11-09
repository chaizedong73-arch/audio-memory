"""Gateway credential storage; consumers do not derive credential file paths."""
import os
from pathlib import Path
import re
import secrets


def _path(root):
    return Path(root) / 'out' / 'ai-gateway' / 'access-token'


def read_gateway_token(root):
    return _path(root).read_text(encoding='ascii').strip()


def load_or_create_gateway_token(root):
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = read_gateway_token(root)
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
            raise ValueError('Invalid gateway token file; inspect it before starting.')
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(fd, 'w', encoding='ascii') as output:
            output.write(token)
    return token
