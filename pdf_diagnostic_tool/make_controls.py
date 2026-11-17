"""Generate explicitly unvalidated derivative controls; never overwrite a file."""
import argparse
import hashlib
import json
from pathlib import Path
import pikepdf

def make(october, working, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    records = []
    for name, source, page_source, single in [
        ('october_resaved.pdf', october, None, False),
        ('october_base_working_page12.pdf', october, working, False),
        ('single_october12.pdf', october, None, True),
        ('single_working12.pdf', working, None, True),
    ]:
        with pikepdf.open(source, attempt_recovery=False) as doc:
            if len(doc.pages) < 12: raise ValueError('Controls require physical page 12')
            if single:
                target = pikepdf.Pdf.new()
                target.pages.append(doc.pages[11])
                # Deliberately untagged stand-alone controls. These are not remediation masters.
                if '/StructParents' in target.pages[0].obj:
                    del target.pages[0].obj['/StructParents']
                target.save(out/name)
                target.close()
            elif page_source:
                with pikepdf.open(page_source, attempt_recovery=False) as donor:
                    doc.pages[11] = donor.pages[11]
                    # Untagged page's stale index must not accidentally address October's ParentTree.
                    if '/StructParents' in doc.pages[11].obj:
                        del doc.pages[11].obj['/StructParents']
                    doc.save(out/name)
            else:
                doc.save(out/name)
        records.append({'file': name, 'sha256': hashlib.sha256((out/name).read_bytes()).hexdigest(),
                        'bytes': (out/name).stat().st_size, 'acrobat_result': 'NOT_RUN',
                        'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                        'donor_sha256': hashlib.sha256(Path(page_source).read_bytes()).hexdigest() if page_source else None,
                        'changes': 'reserialized; single-page outputs untagged; replacement page has StructParents removed' if single or page_source else 'reserialized only'})
    (out/'controls.json').write_text(json.dumps({'schema': 'nsse-controls/1', 'serializer': 'pikepdf '+pikepdf.__version__,
        'warning': 'All derivative controls are untested in Acrobat. Untouched October success must be reconfirmed; if resaved October fails, stop interpreting rewritten controls.', 'cases': records}, indent=2), encoding='utf-8')
    return records

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--october', type=Path, required=True)
    p.add_argument('--working', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    make(a.october, a.working, a.out)
