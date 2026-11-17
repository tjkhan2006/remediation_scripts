"""Export current object definitions for selected file-local object numbers."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import pikepdf
from diagnostic import pack

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pdf', type=Path)
    p.add_argument('objects', nargs='+', help='number or number:generation, e.g. 106864:0')
    p.add_argument('--streams', action='store_true', help='Include decoded stream bytes as base64')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.resolve() == a.pdf.resolve() or a.out.suffix.lower() == '.pdf': p.error('Choose a separate JSON output')
    source_hash = hashlib.sha256(a.pdf.read_bytes()).hexdigest()
    records = []
    with pikepdf.open(a.pdf, attempt_recovery=False) as doc:
        for value in a.objects:
            parts = value.split(':')
            number, generation = int(parts[0]), int(parts[1]) if len(parts) == 2 else 0
            obj = doc.get_object((number, generation))
            row = {'ref': f'{number} {generation} R', 'value': pack(obj, top=True)}
            if a.streams and isinstance(obj, pikepdf.Stream):
                row['decoded_base64'] = base64.b64encode(obj.read_bytes()).decode('ascii')
            records.append(row)
    if hashlib.sha256(a.pdf.read_bytes()).hexdigest() != source_hash: raise RuntimeError('Source changed during export')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({'source_sha256': source_hash, 'objects': records,
                               'scope': 'Current object definitions only; not a historical incremental revision parser.'}, indent=2), encoding='utf-8')
