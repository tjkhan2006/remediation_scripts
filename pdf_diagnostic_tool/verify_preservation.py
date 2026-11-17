"""Compare all-page rendering, text, links and existing tag records; does not prove Acrobat success."""
import argparse
import hashlib
import json
from pathlib import Path
import fitz
from diagnostic import inventory

def sha(data): return hashlib.sha256(data).hexdigest()
def visual(a, b, dpi=96):
    rows = []
    with fitz.open(a) as left, fitz.open(b) as right:
        for i in range(max(len(left), len(right))):
            if i >= min(len(left), len(right)):
                rows.append({'page': i+1, 'missing_page': True})
                continue
            def snap(page):
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                links = [{k:v for k,v in link.items() if k not in ('xref', 'id')} for link in page.get_links()]
                return {'pixels_sha256': sha(pix.samples), 'width': pix.width, 'height': pix.height,
                        'text_sha256': sha(page.get_text().encode()), 'links': str(links), 'rect': str(page.rect)}
            x, y = snap(left[i]), snap(right[i])
            rows.append({'page': i+1, 'equal': x == y, 'before': x, 'after': y})
    return rows

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('before', type=Path)
    p.add_argument('after', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--dpi', type=int, default=96)
    a = p.parse_args()
    if a.out.resolve() in (a.before.resolve(), a.after.resolve()) or a.out.suffix.lower() == '.pdf': p.error('Choose a separate JSON output')
    if not 36 <= a.dpi <= 600: p.error('DPI must be between 36 and 600')
    x, y = inventory(a.before), inventory(a.after)
    # Conservatively compare all baseline records at their logical paths. Insertions and
    # reference renumbering can trigger review; counts alone never imply preservation.
    old = {v['path']: v for v in x['structure_nodes'].values()}
    new = {v['path']: v for v in y['structure_nodes'].values()}
    changed = [k for k in old if old[k] != new.get(k)]
    pages = visual(a.before, a.after, a.dpi)
    result = {'schema': 'nsse-preservation/1', 'source_before': x['source'], 'source_after': y['source'],
              'render_engine': fitz.VersionBind, 'dpi': a.dpi,
              'before_reachable_tags': len(old), 'after_reachable_tags': len(new),
              'baseline_tag_paths_needing_review': changed, 'pages': pages,
              'all_page_snapshots_equal': all(r.get('equal', False) for r in pages),
              'note': 'Path/reference changes require manual semantic review. Pixel equality is limited to this renderer and DPI. This is not PDF/UA validation and cannot establish Fix Reading Order success.'}
    # Verify that neither PDF changed during the entire comparison.
    for path, inv in ((a.before, x), (a.after, y)):
        if sha(path.read_bytes()) != inv['source']['sha256']: raise RuntimeError('Source changed')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'all_page_snapshots_equal': result['all_page_snapshots_equal'], 'tag_paths_needing_review': len(changed)}))
