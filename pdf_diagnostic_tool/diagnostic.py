"""Read-only PDF structure evidence collection. Never saves a PDF."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
import sys
import pikepdf as pdf

VERSION = '0.1.0'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def ref(obj):
    if isinstance(obj, pdf.Object) and obj.is_indirect:
        return f'{obj.objgen[0]} {obj.objgen[1]} R'
    return None

def pack(obj, depth=0, top=False):
    """Keep references, never recursively follow arbitrary PDF graphs."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Decimal):
        return {'decimal': str(obj)}
    if ref(obj) and not top:
        return {'ref': ref(obj)}
    if depth > 64:
        return {'truncated': 'depth_limit'}
    if isinstance(obj, pdf.Stream):
        try:
            decoded = digest(obj.read_bytes())
        except Exception as e:
            decoded = {'error': str(e)}
        return {'dictionary': pack(obj.stream_dict, depth+1, True),
                'raw_sha256': digest(obj.read_raw_bytes()), 'decoded_sha256': decoded}
    if isinstance(obj, pdf.Dictionary):
        return {str(k): pack(v, depth+1) for k, v in sorted(obj.items())}
    if isinstance(obj, pdf.Array):
        return [pack(v, depth+1) for v in obj]
    if isinstance(obj, pdf.String):
        return {'text': str(obj), 'hex': bytes(obj).hex()}
    if isinstance(obj, pdf.Name):
        return str(obj)
    try:
        return float(obj)
    except (TypeError, ValueError):
        return str(obj)

def array(obj):
    return list(obj) if isinstance(obj, pdf.Array) else ([] if obj is None else [obj])

def identity(obj):
    return ref(obj) or json.dumps(pack(obj, top=True), sort_keys=True)

def inherited(obj, key):
    seen = set()
    while isinstance(obj, pdf.Dictionary):
        ident = identity(obj)
        if ident in seen:
            break
        seen.add(ident)
        if key in obj:
            return obj[key]
        obj = obj.get('/Parent')
    return None

def flatten_tree(root, field, issues, label):
    """Read number/name tree leaves, retaining duplicates and validating bounds."""
    pairs, seen = [], set()
    pending = [(root, 0)] if root is not None else []
    while pending:
        node, depth = pending.pop()
        if not isinstance(node, pdf.Dictionary):
            issues.append({'kind': label+'_invalid_node', 'object': ref(node)})
            continue
        ident = identity(node)
        if ident in seen or depth > 128:
            issues.append({'kind': label+'_cycle_or_shared_node', 'object': ref(node)})
            continue
        seen.add(ident)
        vals = array(node.get(field))
        if len(vals) % 2:
            issues.append({'kind': label+'_odd_leaf', 'object': ref(node)})
        keys = []
        for i in range(0, len(vals)-1, 2):
            key = int(vals[i]) if field == '/Nums' else bytes(vals[i]).hex()
            pairs.append((key, vals[i+1]))
            keys.append(key)
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            issues.append({'kind': label+'_unordered_or_duplicate_leaf', 'object': ref(node)})
        if keys and node.get('/Limits') is not None:
            lim = array(node['/Limits'])
            lim = [int(x) if field == '/Nums' else bytes(x).hex() for x in lim]
            if lim != [keys[0], keys[-1]]:
                issues.append({'kind': label+'_incorrect_limits', 'object': ref(node)})
        pending.extend((kid, depth+1) for kid in reversed(array(node.get('/Kids'))))
    counts = Counter(k for k, _ in pairs)
    for k, n in counts.items():
        if n > 1:
            issues.append({'kind': label+'_duplicate_key', 'key': k, 'count': n})
    if [k for k, _ in pairs] != sorted(k for k, _ in pairs):
        issues.append({'kind': label+'_global_order'})
    return pairs

def logical_tree(root, issues):
    nodes, content = {}, []
    pending = [(k, ref(root), None, f'root/{i}', 0) for i, k in enumerate(array(root.get('/K')))] if root else []
    while pending:
        obj, parent, pg, path, depth = pending.pop()
        if depth > 256:
            issues.append({'kind': 'structure_depth_limit', 'path': path})
            continue
        if not isinstance(obj, pdf.Dictionary) or obj.get('/S') is None:
            issues.append({'kind': 'unexpected_root_kid', 'path': path})
            continue
        key = ref(obj) or path
        if key in nodes:
            issues.append({'kind': 'structure_cycle_or_shared_kid', 'object': key})
            continue
        pg = ref(obj.get('/Pg')) or pg
        nodes[key] = {'ref': ref(obj), 'path': path, 'parent': parent, 'page': pg,
                      'dictionary': pack(obj, top=True)}
        if ref(obj.get('/P')) != parent:
            issues.append({'kind': 'parent_mismatch', 'object': key, 'expected': parent,
                           'actual': ref(obj.get('/P'))})
        for i, kid in enumerate(array(obj.get('/K'))):
            if isinstance(kid, pdf.Dictionary) and kid.get('/S') is not None:
                pending.append((kid, key, pg, f'{path}/{i}', depth+1))
            elif isinstance(kid, int):
                content.append({'parent': key, 'mcid': kid, 'owner': pg, 'page': pg, 'kind': 'integer'})
            elif isinstance(kid, pdf.Dictionary):
                if kid.get('/MCID') is not None:
                    content.append({'parent': key, 'mcid': int(kid['/MCID']),
                                    'owner': ref(kid.get('/Stm')) or ref(kid.get('/Pg')) or pg,
                                    'page': ref(kid.get('/Pg')) or pg, 'kind': 'MCR', 'dictionary': pack(kid, top=True)})
                elif kid.get('/Type') == pdf.Name('/OBJR'):
                    content.append({'parent': key, 'object': ref(kid.get('/Obj')), 'kind': 'OBJR',
                                    'page': ref(kid.get('/Pg')) or pg, 'dictionary': pack(kid, top=True)})
                else:
                    issues.append({'kind': 'unknown_structure_kid', 'parent': key, 'kid': pack(kid, top=True)})
            else:
                issues.append({'kind': 'unknown_structure_kid', 'parent': key, 'kid': pack(kid)})
    return nodes, content

def inspect_content(page, number, issues):
    sequences, owners, invocations = [], {}, []
    def walk(source, owner, resources, chain, enclosing_artifact=False):
        owner_ref = ref(owner)
        if owner_ref in chain or len(chain) > 64:
            issues.append({'kind': 'form_cycle_or_depth_limit', 'page': number, 'owner': owner_ref})
            return
        owner_key = owner_ref or f'page:{number}:direct'
        # A reused Form has one MCID namespace; occurrences are logged separately.
        if owner_key in owners:
            invocations.append({'owner': owner_key, 'chain': chain, 'artifact': enclosing_artifact})
            return
        owners[owner_key] = {'ref': owner_ref, 'struct_parents': pack(owner.get('/StructParents')),
                             'kind': 'page' if isinstance(source, pdf.Page) else 'form'}
        stack = []
        try:
            instructions = pdf.parse_content_stream(source)
        except Exception as e:
            issues.append({'kind': 'content_parse_error', 'page': number, 'owner': owner_ref, 'error': str(e)})
            return
        operators_hash = hashlib.sha256()
        unmarked_hash = hashlib.sha256()
        for ordinal, ins in enumerate(instructions):
            if isinstance(ins, pdf.ContentStreamInlineImage):
                # Inline image bytes are covered by decoded content-stream hashes.
                owners[owner_key]['has_inline_images'] = True
                continue
            operands, op = ins.operands, str(ins.operator)
            record = json.dumps([op, [pack(x) for x in operands]], sort_keys=True).encode()
            operators_hash.update(record+b'\n')
            if op not in ('BDC', 'BMC', 'EMC'):
                unmarked_hash.update(record+b'\n')
            if op in ('BDC', 'BMC'):
                props, prop_name = None, None
                if op == 'BDC' and len(operands) > 1:
                    props = operands[1]
                    if isinstance(props, pdf.Name):
                        prop_name = str(props)
                        props = resources.get('/Properties', {}).get(props)
                        if props is None:
                            issues.append({'kind': 'unresolved_property', 'page': number, 'name': prop_name})
                raw_mcid = props.get('/MCID') if isinstance(props, pdf.Dictionary) else None
                mcid = raw_mcid if isinstance(raw_mcid, int) and not isinstance(raw_mcid, bool) and raw_mcid >= 0 else None
                if raw_mcid is not None and mcid is None:
                    issues.append({'kind': 'invalid_mcid', 'page': number, 'value': pack(raw_mcid)})
                tag = str(operands[0]) if operands else None
                row = {'page': number, 'owner': owner_key, 'ordinal': ordinal, 'operator': op,
                       'tag': tag, 'property_name': prop_name, 'properties': pack(props, top=True),
                       'mcid': mcid, 'depth': len(stack), 'artifact': tag == '/Artifact',
                       'inside_artifact': enclosing_artifact or any(x['artifact'] for x in stack),
                       'text_show_operators': 0}
                sequences.append(row)
                stack.append(row)
            elif op == 'EMC':
                if stack:
                    stack.pop()['end_ordinal'] = ordinal
                else:
                    issues.append({'kind': 'unmatched_EMC', 'page': number, 'owner': owner_ref, 'ordinal': ordinal})
            elif op in ('Tj', 'TJ', "'", '"'):
                for entry in stack:
                    entry['text_show_operators'] += 1
            elif op == 'Do' and operands:
                form = resources.get('/XObject', {}).get(operands[0])
                if isinstance(form, pdf.Stream) and form.get('/Subtype') == pdf.Name('/Form'):
                    walk(form, form, form.get('/Resources', resources), chain+[owner_key],
                         enclosing_artifact or any(x['artifact'] for x in stack))
        owners[owner_key]['operators_sha256_excluding_inline_images'] = operators_hash.hexdigest()
        owners[owner_key]['operators_without_marked_content_sha256_excluding_inline_images'] = unmarked_hash.hexdigest()
        for entry in stack:
            issues.append({'kind': 'unclosed_marked_content', 'page': number,
                           'owner': owner_ref, 'ordinal': entry['ordinal']})
    resources = inherited(page.obj, '/Resources') or pdf.Dictionary()
    walk(page, page.obj, resources, [])
    return sequences, owners, invocations

def inventory(path, objects=False):
    path = Path(path).resolve()
    before = digest(path.read_bytes())
    issues = []
    result = {'schema': 'nsse-diagnostic/1', 'tool_version': VERSION,
              'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'source': {'filename': path.name, 'sha256': before, 'bytes': path.stat().st_size},
              'scope': 'all pages, reachable structure, ParentTree, IDTree; Form XObjects reached by Do; no annotation appearance content parsing',
              'issues': issues}
    with pdf.open(path, attempt_recovery=False) as doc:
        root = doc.Root.get('/StructTreeRoot')
        nodes, kids = logical_tree(root, issues)
        parents = flatten_tree(root.get('/ParentTree') if root else None, '/Nums', issues, 'parent_tree')
        ids = flatten_tree(root.get('/IDTree') if root else None, '/Names', issues, 'id_tree')
        parent_index = dict(parents)
        forward = defaultdict(list)
        for kid in kids:
            if 'mcid' in kid:
                forward[(kid['owner'], kid['mcid'])].append(kid['parent'])
        pages, sequences, all_owners = [], [], {}
        for number, page in enumerate(doc.pages, 1):
            seqs, owners, calls = inspect_content(page, number, issues)
            all_owners.update(owners)
            for s in seqs:
                if s['mcid'] is None:
                    s['association'] = 'no_mcid'
                    continue
                sp = owners[s['owner']]['struct_parents']
                entries = parent_index.get(sp) if isinstance(sp, int) else None
                target = entries[s['mcid']] if isinstance(entries, pdf.Array) and s['mcid'] < len(entries) else None
                s['parent_tree_target'] = ref(target)
                s['forward_parents'] = forward.get((s['owner'], s['mcid']), [])
                s['target_reachable'] = ref(target) in nodes if target is not None else False
                s['association'] = ('missing_parent_tree_entry' if target is None else
                                    'unreachable_parent' if not s['target_reachable'] else
                                    'forward_reverse_mismatch' if ref(target) not in s['forward_parents'] else 'linked')
                if s['association'] != 'linked':
                    issues.append({'kind': s['association'], 'page': number, 'owner': s['owner'],
                                   'mcid': s['mcid'], 'target': ref(target)})
                if s['artifact'] or s['inside_artifact']:
                    issues.append({'kind': 'mcid_in_artifact_context', 'page': number, 'owner': s['owner'], 'mcid': s['mcid']})
            counts = Counter((s['owner'], s['mcid']) for s in seqs if s['mcid'] is not None)
            for (owner, mcid), count in counts.items():
                if count > 1:
                    issues.append({'kind': 'duplicate_mcid', 'page': number, 'owner': owner, 'mcid': mcid, 'count': count})
            streams = array(page.obj.get('/Contents'))
            pages.append({'page': number, 'ref': ref(page.obj), 'struct_parents': pack(page.obj.get('/StructParents')),
                          'mediabox': pack(inherited(page.obj, '/MediaBox')), 'resources': pack(inherited(page.obj, '/Resources'), top=True),
                          'content_streams': [{'ref': ref(s), **pack(s, top=True)} for s in streams if isinstance(s, pdf.Stream)],
                          'annotations': [pack(a, top=True) for a in array(page.obj.get('/Annots'))],
                          'marked_content': len(seqs), 'mcid_occurrences': sum(s['mcid'] is not None for s in seqs),
                          'association_counts': dict(Counter(s['association'] for s in seqs)), 'form_reuses': calls})
            sequences.extend(seqs)
        observed = {(s['owner'], s['mcid']) for s in sequences if s['mcid'] is not None}
        for key, tags in forward.items():
            if key not in observed:
                issues.append({'kind': 'forward_reference_without_observed_content', 'owner': key[0], 'mcid': key[1], 'parents': tags,
                               'note': 'May be outside parsed scope; annotation appearances are not parsed.'})
            if len(tags) > 1:
                issues.append({'kind': 'multiple_forward_parents', 'owner': key[0], 'mcid': key[1], 'parents': tags})
        next_key = root.get('/ParentTreeNextKey') if root else None
        if parents and (not isinstance(next_key, int) or next_key <= max(k for k, _ in parents)):
            issues.append({'kind': 'parent_tree_next_key_missing_or_not_above_max', 'value': pack(next_key)})
        classmap = root.get('/ClassMap', {}) if root else {}
        rolemap = root.get('/RoleMap', {}) if root else {}
        for role in rolemap:
            seen_roles, current = set(), role
            while current in rolemap:
                if str(current) in seen_roles:
                    issues.append({'kind': 'role_map_cycle', 'role': str(role)})
                    break
                seen_roles.add(str(current))
                current = rolemap[current]
                if not isinstance(current, pdf.Name):
                    issues.append({'kind': 'invalid_role_map_value', 'role': str(role)})
                    break
        for key, node in nodes.items():
            for cl in array(node['dictionary'].get('/C')):
                if isinstance(cl, str) and cl.startswith('/') and cl not in classmap:
                    issues.append({'kind': 'missing_class_definition', 'object': key, 'class': cl})
        id_rows = []
        for key, target in ids:
            current_id = target.get('/ID') if isinstance(target, pdf.Dictionary) else None
            state = 'unreachable' if ref(target) not in nodes else ('matching' if isinstance(current_id, pdf.String) and bytes(current_id).hex() == key else 'stale_alias')
            id_rows.append({'id_hex': key, 'target': ref(target), 'state': state})
        id_index = dict(ids)
        for key, node in nodes.items():
            id_value = node['dictionary'].get('/ID')
            if isinstance(id_value, dict) and 'hex' in id_value and ref(id_index.get(id_value['hex'])) != key:
                issues.append({'kind': 'structure_id_lookup_mismatch', 'object': key, 'id_hex': id_value['hex']})
        result.update({'pdf_version': str(doc.pdf_version), 'encrypted': doc.is_encrypted,
                       'metadata': pack(doc.docinfo, top=True), 'catalog': pack(doc.Root, top=True),
                       'structure_root': pack(root, top=True), 'structure_nodes': nodes, 'structure_content': kids,
                       'parent_tree': [{'key': k, 'value': pack(v, top=True)} for k, v in parents],
                       'parent_tree_reference_states': dict(Counter('reachable' if ref(v) in nodes else 'unreachable' for _, vals in parents for v in array(vals) if v is not None)),
                       'id_tree': id_rows, 'pages': pages, 'sequences': sequences, 'owners': all_owners})
        if objects:
            # Dictionary contents retain refs. Streams hashed without embedding document text.
            result['objects'] = {ref(obj): {'sha256': digest(json.dumps(pack(obj, top=True), sort_keys=True, ensure_ascii=True).encode())}
                                 for obj in doc.objects if ref(obj)}
        result['parser_warnings'] = doc.get_warnings()
        result['summary'] = {'pages': len(pages), 'reachable_tags': len(nodes),
                             'structure_types': dict(Counter(n['dictionary'].get('/S') for n in nodes.values())),
                             'mcid_occurrences': sum(p['mcid_occurrences'] for p in pages),
                             'parent_tree_keys': len(parents), 'id_tree_entries': len(ids),
                             'id_states': dict(Counter(r['state'] for r in id_rows)),
                             'association_counts': dict(Counter(s['association'] for s in sequences)),
                             'issue_counts': dict(Counter(i['kind'] for i in issues))}
    result['source']['sha256_after'] = digest(path.read_bytes())
    if result['source']['sha256_after'] != before:
        raise RuntimeError('Source changed during analysis; evidence discarded')
    return result

def compare(a, b):
    """Object refs are local to each file; do not infer identity after a rewrite."""
    changes = {}
    for field in ('catalog', 'metadata', 'structure_root', 'structure_nodes', 'structure_content',
                  'parent_tree', 'id_tree', 'pages', 'sequences', 'owners', 'objects'):
        left, right = a.get(field), b.get(field)
        if left == right:
            continue
        if isinstance(left, dict) and isinstance(right, dict):
            added = {k: right[k] for k in right.keys()-left.keys()}
            removed = {k: left[k] for k in left.keys()-right.keys()}
            modified = {k: {'before': left[k], 'after': right[k]} for k in left.keys() & right.keys() if left[k] != right[k]}
            changes[field] = {'added': added, 'removed': removed, 'modified': modified}
        else:
            changes[field] = {'before': left, 'after': right}
    return {'schema': 'nsse-comparison/1', 'before': a['source'], 'after': b['source'],
            'warning': 'Object numbers are file-local. Renumbering causes noisy reference diffs; compare page operator sequences, paths, IDs and semantic relationships before attributing changes.',
            'summary_before': a['summary'], 'summary_after': b['summary'], 'changes': changes,
            'acrobat_validation': 'NOT RUN; static differences cannot prove repair or private UI call sequence'}

def report(data, path):
    title = 'PDF tagging diagnostic report'
    summary = data.get('summary') or {'before': data.get('summary_before'), 'after': data.get('summary_after')}
    rows = ''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in
                   (p['page'], p['marked_content'], p['mcid_occurrences'], p['association_counts']))+'</tr>' for p in data.get('pages', []))
    text = json.dumps(data, indent=2, ensure_ascii=True)
    source = html.escape(json.dumps(data.get('source') or {'before': data.get('before'), 'after': data.get('after')}, indent=2))
    issue_rows = ''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
                        (r.get('page', ''), r['kind'], r.get('owner', r.get('object', '')), r.get('mcid', ''), r.get('target', '')))+'</tr>' for r in data.get('issues', []))
    tag_rows = ''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
                      (k, n['dictionary'].get('/S'), n.get('parent'), n.get('page'), n.get('path')))+'</tr>' for k, n in data.get('structure_nodes', {}).items())
    details = []
    for page in data.get('pages', []):
        pn = page['page']
        seq_rows = ''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
                          (r['ordinal'], r['tag'], r['operator'], r['owner'], r['mcid'], r['association'], r.get('parent_tree_target', ''), r['text_show_operators']))+'</tr>'
                          for r in data.get('sequences', []) if r['page'] == pn)
        details.append(f'<details><summary>Page {pn}: {page["marked_content"]} containers, {page["mcid_occurrences"]} MCID occurrences</summary><table><tr><th>Operator index</th><th>Tag name</th><th>Operator</th><th>Owner</th><th>MCID</th><th>Association</th><th>ParentTree target</th><th>Enclosed text-show operators</th></tr>{seq_rows}</table></details>')
    page_details = ''.join(details)
    Path(path).write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:1rem}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}td,th{{border:1px solid #aaa;padding:.4rem}}table{{border-collapse:collapse}}input{{width:80%;padding:.5rem}}</style>
<h1>{title}</h1><p>Read-only static analysis. Acrobat validation has not been performed. No repair is established.</p>
<h2>Source identity</h2><pre>{source}</pre><h2>Summary</h2><pre>{html.escape(json.dumps(summary, indent=2))}</pre>
<h2>Page inventory</h2><table><tr><th>Page</th><th>Containers</th><th>MCIDs</th><th>Associations</th></tr>{rows}</table>
<h2>How to read associations</h2><p>Linked means observed forward and reverse references agree on a reachable tag. No MCID means no marked-content identity was present; ordinary artifacts and untagged content may legitimately have none. Missing or unreachable parents require interpretation against the selected tagging operation. Counts alone do not establish accessibility.</p>
<h2>Issue records</h2><details><summary>Expand all issue records</summary><table><tr><th>Page</th><th>Finding</th><th>Owner/object</th><th>MCID</th><th>Target</th></tr>{issue_rows}</table></details>
<h2>Per-page marked content</h2>{page_details}
<h2>Reachable logical tags</h2><details><summary>Expand tag inventory (file-local references)</summary><table><tr><th>Reference</th><th>Type</th><th>Parent</th><th>Page reference</th><th>Logical path</th></tr>{tag_rows}</table></details>
<h2>Full evidence</h2><p>Companion JSON is the machine-readable source. This section includes every exported record.</p>
<details><summary>Expand full document analytics</summary><pre>{html.escape(text)}</pre></details></html>''', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    audit = sub.add_parser('audit')
    audit.add_argument('pdf', type=Path)
    audit.add_argument('--objects', action='store_true', help='Fingerprint every current indirect object (slower)')
    audit.add_argument('--out', type=Path, required=True)
    audit.add_argument('--html', type=Path)
    audit.add_argument('--jsonl', type=Path, help='Structured per-record evidence log')
    diff = sub.add_parser('compare')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    diff.add_argument('--out', type=Path, required=True)
    diff.add_argument('--html', type=Path)
    args = parser.parse_args()
    if args.command == 'audit' and (args.out.resolve() == args.pdf.resolve() or (args.html and args.html.resolve() == args.pdf.resolve())):
        parser.error('Output must not overwrite the source PDF')
    if args.command == 'compare' and any(p.resolve() in (args.before.resolve(), args.after.resolve()) for p in (args.out, args.html) if p):
        parser.error('Output must not overwrite input evidence')
    extra = getattr(args, 'jsonl', None)
    if extra and (extra.resolve() in (args.out.resolve(), args.pdf.resolve()) or extra.suffix.lower() == '.pdf' or (args.html and extra.resolve() == args.html.resolve())):
        parser.error('JSONL requires a separate non-PDF output path')
    if args.html and args.html.resolve() == args.out.resolve():
        parser.error('JSON and HTML require different paths')
    # Also reject any PDF output suffix to avoid accidental source replacement.
    if any(p.suffix.lower() == '.pdf' for p in (args.out, args.html) if p):
        parser.error('Reports cannot be written as PDFs')
    result = inventory(args.pdf, args.objects) if args.command == 'audit' else compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding='utf-8')
    if extra:
        extra.parent.mkdir(parents=True, exist_ok=True)
        with extra.open('w', encoding='utf-8') as log:
            log.write(json.dumps({'event': 'session', 'source': result['source'], 'summary': result['summary']})+'\n')
            for kind in ('pages', 'sequences', 'issues'):
                for record in result[kind]:
                    log.write(json.dumps({'event': kind, **record})+'\n')
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        report(result, args.html)
    print(json.dumps(result.get('summary', {'changed_sections': list(result['changes'])}) if 'changes' in result else result['summary'], indent=2))

if __name__ == '__main__':
    main()
