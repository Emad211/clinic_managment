from __future__ import annotations

import base64
import gzip
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
mode = sys.argv[3]
raw = ''.join(source.read_text(encoding='utf-8').split())
raw += '=' * (-len(raw) % 4)
data = base64.b64decode(raw, validate=False)
if mode == 'gzip':
    data = gzip.decompress(data)
target.write_bytes(data)
print(f'{source}: ok ({len(data)} bytes)')
