"""Create independent byte-identical Acrobat test inputs and an editable run manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

CASES = [('oct_fro', 'october', 'Fix Reading Order -> Text/Paragraph'),
         ('working_save_only', 'working', 'Save As without tagging'),
         ('working_fro', 'working', 'Fix Reading Order -> Text/Paragraph'),
         ('working_selection', 'working', 'Create Tag from Selection'),
         ('working_seed_then_fro', 'working', 'Create Tag from Selection; save/reopen; FRO on adjacent untagged text')]

def prepare(october, working, out):
    out = Path(out)
    # New directory only: prevent overwriting any earlier capture or source.
    out.mkdir(parents=True, exist_ok=False)
    sources = {'october': Path(october), 'working': Path(working)}
    manifest = {'schema': 'nsse-run/1', 'acrobat_build': '2026.002.22031', 'architecture': 'x64',
                'windows_version': None, 'sdk_header_manifest': None, 'plugin_sha256': None,
                'note': 'Reported build from screenshot; verify at execution. Record both physical page number and displayed page label.', 'cases': []}
    for label, source, operation in CASES:
        src = sources[source]
        folder = out/label
        folder.mkdir()
        target = folder/'before.pdf'
        shutil.copyfile(src, target)
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise RuntimeError('Copy verification failed')
        manifest['cases'].append({'case': label, 'source_sha256': sha, 'before': str(target.relative_to(out)),
                                  'after': f'{label}/after.pdf', 'operation': operation, 'physical_page': 12,
                                  'displayed_page_label': None, 'selection_text': None, 'selection_rectangle_pdf_points': None,
                                  'timestamp_utc': None, 'result': 'NOT_RUN', 'show_in_tags_result': None,
                                  'save_reopen_persistent': None, 'live_before_log': None, 'live_after_log': None,
                                  'screenshots': [], 'error_verbatim': None})
    (out/'run.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--october', type=Path, required=True)
    p.add_argument('--working', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    prepare(a.october, a.working, a.out)
    print(a.out/'run.json')
