"""Read owner-managed Mac credentials without shell evaluation or value logging."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


LOCAL_CREDENTIALS = {
    'fuyao': ('fuyao.env', 'FUYAO_API_KEY'),
    'tushare': ('tushare.env', 'TUSHARE_TOKEN'),
}


def load_local_credential(provider: str, *, path: Path | None = None) -> str:
    """Use ~/.config/qount/<provider>.env; never evaluate or export its contents."""
    if sys.platform != 'darwin':
        raise ValueError('credential_Mac_only')
    if provider not in LOCAL_CREDENTIALS:
        raise ValueError('credential_unknown_provider')
    filename, name = LOCAL_CREDENTIALS[provider]
    source = path if path is not None else Path.home() / '.config/qount' / filename
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.getuid()):
                raise ValueError('credential_requires_owned_regular_0600')
            text = stream.read(4097)
    except OSError:
        raise ValueError('credential_file_missing_or_unsafe') from None
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if len(text) > 4096 or len(lines) != 1 or not lines[0].startswith(name + '='):
        raise ValueError('credential_format')
    value = lines[0].split('=', 1)[1]
    if not value or any(not 33 <= ord(char) <= 126 for char in value):
        raise ValueError('credential_shape')
    if provider == 'tushare' and not value.isalnum():
        raise ValueError('credential_shape')
    return value
