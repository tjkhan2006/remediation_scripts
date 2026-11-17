"""Record installed SDK declarations and header hashes; compilation is a separate gate."""
import argparse
import hashlib
import json
from pathlib import Path
import re

APIS = ['PDSMCIDGetParent', 'PDSMCGetParent', 'PDSElementGetParent',
        'PDSTreeRootGetElementFromID', 'PDDocGetStructTreeRoot',
        'PDEContainerGetDict', 'PDEContainerGetContent', 'PDEFormGetCosObj']

def inspect(root):
    hits = {name: [] for name in APIS}
    files = []
    for path in sorted(Path(root).rglob('*.h')):
        data = path.read_bytes()
        text = data.decode('utf-8', errors='replace')
        lines = text.splitlines()
        files.append({'file': str(path.relative_to(root)), 'sha256': hashlib.sha256(data).hexdigest()})
        for name in APIS:
            for i, line in enumerate(lines):
                if re.search(r'\b'+name+r'\b', line):
                    hits[name].append({'file': str(path.relative_to(root)), 'line': i+1,
                                       'context': '\n'.join(lines[max(0,i-3):i+10])})
    missing = [n for n, h in hits.items() if not h]
    return {'status': 'MISSING_APIS' if missing else 'DECLARATIONS_LOCATED_COMPILE_CHECK_PENDING',
            'missing': missing, 'headers': files, 'api_occurrences': hits,
            'note': 'Occurrences can include comments/macros. SignatureChecks.cpp must compile against these headers; retain MSBuild logs. This manifest alone does not validate signatures.'}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sdk', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if not a.sdk.is_dir(): p.error('SDK directory not found')
    result = inspect(a.sdk)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(result['status'])
    raise SystemExit(1 if result['missing'] else 0)
