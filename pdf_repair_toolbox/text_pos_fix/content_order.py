"""State-preserving page-content partitioning. No text extraction/recreation."""
from dataclasses import dataclass
import hashlib
import pikepdf as q

SHOW = {'Tj', 'TJ', "'", '"'}
PAINT = {'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*'}
KNOWN = set('q Q cm w J j M d ri i gs m l c v y h re S s f F f* B B* b b* n W W* BT ET Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ Do sh CS cs SC SCN sc scn G g RG rg K k MP DP BMC BDC EMC BX EX'.split()) | SHOW

class Unsupported(ValueError):
    pass

@dataclass
class Plan:
    state: str
    reason: str
    text_count: int = 0
    data: bytes | None = None


def digest(page):
    return hashlib.sha256(q.unparse_content_stream(list(q.parse_content_stream(page)))).hexdigest()


def analyze(page):
    try:
        return _analyze(page)
    except (Unsupported, q.PdfError, ValueError, TypeError, KeyError, IndexError) as exc:
        return Plan('Skipped', str(exc))


def _analyze(page):
    instructions = list(q.parse_content_stream(page))
    if str(page.obj.get('/TextPosFixDigest', '')) == digest(page):
        return Plan('Already repaired', 'Drawing order is already repaired.')
    resources = page.resources
    for font in resources.get('/Font', {}).values():
        if str(font.get('/Subtype')) == '/Type3':
            raise Unsupported('Type 3 fonts may paint arbitrary artwork.')
    # Replaying text across groups/soft masks can change compositing semantics.
    if '/Group' in page.obj:
        raise Unsupported('Page transparency groups require manual review.')
    for state in resources.get('/ExtGState', {}).values():
        if (str(state.get('/SMask', '/None')) != '/None' or
            str(state.get('/BM', '/Normal')) not in ('/Normal', '/Compatible') or
            float(state.get('/ca', 1)) != 1 or float(state.get('/CA', 1)) != 1 or
            '/TR' in state or '/TR2' in state):
            raise Unsupported('Transparency, blending, or transfer functions require manual review.')
    # Text-only Forms move intact; mixed Forms are never silently left behind.
    def form_kinds(stream, seen):
        ident = tuple(stream.objgen)
        if ident in seen:
            raise Unsupported('Cyclic Form XObject references.')
        seen = seen | {ident}
        res = stream.get('/Resources', resources)
        kinds = set()
        if '/Group' in stream:
            raise Unsupported('Nested transparency groups require manual review.')
        for font in res.get('/Font', {}).values():
            if str(font.get('/Subtype')) == '/Type3':
                raise Unsupported('Type 3 fonts in Form artwork require manual review.')
        for inst in q.parse_content_stream(stream):
            if not hasattr(inst, 'operator'):
                kinds.add('art')
                continue
            op = str(inst.operator)
            if op not in KNOWN:
                raise Unsupported('Unknown operator inside Form artwork.')
            if op == 'Tr' and int(inst.operands[0]) >= 4:
                raise Unsupported('Text clipping inside Form artwork requires manual review.')
            if op == 'gs':
                raise Unsupported('Extended graphics state in text Form artwork requires manual review.')
            if op in SHOW:
                kinds.add('text')
            elif op in PAINT or op == 'sh':
                kinds.add('art')
            if op == 'Do':
                child = res.get('/XObject', {}).get(str(inst.operands[0]))
                if child is None:
                    raise Unsupported('Missing nested XObject resource.')
                if str(child.get('/Subtype')) == '/Form':
                    kinds.update(form_kinds(child, seen))
                else:
                    kinds.add('art')
        return kinds

    frames, stack, owners = {}, [], {}
    text_forms = set()
    depth = 0
    in_text = False
    text_count = 0
    def paint(kind):
        for start in stack:
            frames[start]['kinds'].add(kind)
    for i, inst in enumerate(instructions):
        if not hasattr(inst, 'operator'):
            if in_text:
                raise Unsupported('Inline image inside a text object.')
            paint('art')
            continue
        args, op = inst.operands, str(inst.operator)
        if op not in KNOWN:
            raise Unsupported(f'Unsupported drawing operator: {op}')
        if op == 'q':
            depth += 1
        elif op == 'Q':
            depth -= 1
            if depth < 0:
                raise Unsupported('Unbalanced graphics-state stack.')
        elif op == 'BT':
            if in_text:
                raise Unsupported('Nested text objects.')
            in_text = True
        elif op == 'ET':
            if not in_text:
                raise Unsupported('Unbalanced text objects.')
            in_text = False
        elif op == 'Tr' and int(args[0]) >= 4:
            raise Unsupported('Text used as a clipping mask cannot be reordered safely.')
        elif op in ('BDC', 'BMC'):
            props = args[1] if op == 'BDC' else None
            if isinstance(props, q.Name):
                props = resources.get('/Properties', {}).get(str(props))
                if props is None:
                    raise Unsupported('Unresolved marked-content properties.')
            mcid = isinstance(props, q.Dictionary) and '/MCID' in props
            if mcid and any(frames[x]['mcid'] for x in stack):
                raise Unsupported('Nested MCID scopes require manual review.')
            frames[i] = {'mcid': mcid, 'kinds': set(), 'end': None}
            stack.append(i)
        elif op == 'EMC':
            if not stack:
                raise Unsupported('Unbalanced marked content.')
            start = stack.pop()
            frames[start]['end'] = i
            owners[i] = start
        elif op in SHOW:
            if not in_text:
                raise Unsupported('Text drawing outside BT/ET.')
            paint('text')
            text_count += 1
        elif op in PAINT or op == 'sh':
            if in_text:
                raise Unsupported('Artwork inside a text object.')
            paint('art')
        elif op == 'Do':
            if in_text:
                raise Unsupported('XObject inside a text object.')
            obj = resources.get('/XObject', {}).get(str(args[0]))
            if obj is None:
                raise Unsupported('Missing XObject resource.')
            kinds = form_kinds(obj, set()) if str(obj.get('/Subtype')) == '/Form' else {'art'}
            if kinds == {'text', 'art'}:
                raise Unsupported('Mixed text and artwork inside a Form requires manual review.')
            if kinds == {'text'}:
                text_forms.add(i)
                text_count += 1
                paint('text')
            else:
                paint('art')
        elif op == 'DP':
            raise Unsupported('Marked-content point properties require manual review.')
    if depth or stack or in_text:
        raise Unsupported('Unbalanced page content.')
    for frame in frames.values():
        if frame['mcid'] and frame['kinds'] == {'text', 'art'}:
            raise Unsupported('An MCID contains both text and artwork; tag ownership cannot be split safely.')
    if not text_count:
        return Plan('No text', 'No page text drawing operations found.')
    base, foreground = [], []
    for i, inst in enumerate(instructions):
        if not hasattr(inst, 'operator'):
            base.append(inst)
            continue
        args, op = inst.operands, str(inst.operator)
        start = i if i in frames else owners.get(i)
        if start is not None and frames[start]['mcid']:
            (foreground if frames[start]['kinds'] == {'text'} else base).append(inst)
            continue
        if i in text_forms:
            foreground.append(inst)
            continue
        if op in SHOW:
            foreground.append(inst)
            # Quote operators also change persistent text-state parameters.
            if op == '"':
                base.extend([([args[0]], q.Operator('Tw')), ([args[1]], q.Operator('Tc'))])
            continue
        base.append(inst)
        if op in PAINT:
            foreground.append(([], q.Operator('n')))
        elif op not in ('Do', 'sh', 'MP'):
            foreground.append(inst)
    # q/Q isolate passes so state inherited from the first pass cannot leak.
    output = [([], q.Operator('q'))] + base + [([], q.Operator('n')), ([], q.Operator('Q')), ([], q.Operator('q'))] + foreground + [([], q.Operator('n')), ([], q.Operator('Q'))]
    return Plan('Ready', 'Text can be brought above page artwork.', text_count, q.unparse_content_stream(output))
