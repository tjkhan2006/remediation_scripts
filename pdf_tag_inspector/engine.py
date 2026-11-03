"""Tagged PDF inspection and metadata editing, with save-to-copy semantics."""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import csv
import json

import pikepdf
import pymupdf as fitz
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1, dict_value, stream_value
from pdfminer.psparser import PSLiteral, literal_name


def object_id(obj):
    return tuple(obj.objgen) if isinstance(obj, pikepdf.Object) and obj.is_indirect else None


def items(value):
    if value is None:
        return []
    return list(value) if isinstance(value, pikepdf.Array) else [value]


def name(value):
    return str(value or '').lstrip('/')


def describe_value(value, depth=0):
    if value is None:
        return '(not set)'
    oid = object_id(value)
    if oid:
        return f'{oid[0]} {oid[1]} R' + (' (stream)' if isinstance(value, pikepdf.Stream) else '')
    if depth > 6:
        return '(nested value; depth limit)'
    if isinstance(value, pikepdf.Dictionary):
        return '<< ' + ' '.join(f'{k} {describe_value(v, depth+1)}' for k, v in value.items()) + ' >>'
    if isinstance(value, pikepdf.Array):
        return '[ ' + ' '.join(describe_value(v, depth+1) for v in value) + ' ]'
    return str(value)


def describe_dictionary(obj):
    return '\n'.join(f'{k}: {describe_value(v)}' for k, v in sorted(obj.items()))


@dataclass(frozen=True)
class ContentRef:
    page: int | None
    mcid: int | None = None
    stream: int = 0
    rect: tuple | None = None


@dataclass
class Tag:
    id: int
    parent: int | None
    role: str
    mapped_role: str
    path: str
    object_ref: str
    title: str = ''
    alt: str = ''
    actual_text: str = ''
    language: str = ''
    attributes: str = ''
    children: list[int] = field(default_factory=list)
    refs: list[ContentRef] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    end: int = 0
    expansion: str = ''
    identifier: str = ''
    dictionary: str = ''
    classes: str = ''
    inherited_language: str = ''

    def matches(self, query='', role='All tags', page=None, missing_alt=False):
        return ((role == 'All tags' or role in (self.role, self.mapped_role))
                and (page is None or page in self.pages)
                and (not missing_alt or (self.mapped_role == 'Figure' and not self.alt.strip()))
                and (not query or query.casefold() in ' '.join((self.role, self.mapped_role,
                     self.path, self.title, self.alt, self.actual_text, self.language,
                     self.attributes, self.object_ref, self.identifier, self.expansion)).casefold()))


class TaggedDevice(PDFPageAggregator):
    """Associate PDFMiner geometry with scoped MCIDs, including nested Form XObjects."""
    def __init__(self, manager):
        super().__init__(manager, laparams=None)
        self.stream_id = 0
        self.marks = []
        self.geometry = defaultdict(list)
        self.text = defaultdict(list)
        self.colors = defaultdict(set)

    def begin_tag(self, tag, props=None):
        props = resolve1(props)
        mcid = props.get('MCID') if isinstance(props, dict) else None
        mcid = resolve1(mcid)
        self.marks.append((self.stream_id, mcid) if isinstance(mcid, int) else None)

    def end_tag(self):
        if self.marks:
            self.marks.pop()

    def capture(self, obj, gstate=None):
        for key in set(k for k in self.marks if k is not None):
            self.geometry[key].append(tuple(obj.bbox))
            state = gstate or getattr(obj, 'graphicstate', None)
            if state is not None:
                self.colors[key].add(f'Fill: {state.ncs.name} {state.ncolor} | Stroke: {state.scs.name} {state.scolor} | Intent: {literal_name(state.intent) if isinstance(state.intent, PSLiteral) else "not explicitly set"}')
            if hasattr(obj, 'stream'):
                self.colors[key].add(f'Image color space: {obj.stream.get("ColorSpace", "not specified / image mask")} | Intent: {obj.stream.get("Intent", "not explicitly set")}')
            if hasattr(obj, 'get_text'):
                self.text[key].append(obj.get_text())

    def render_char(self, *args, **kwargs):
        result = super().render_char(*args, **kwargs)
        self.capture(self.cur_item._objs[-1])
        return result

    def render_image(self, *args, **kwargs):
        super().render_image(*args, **kwargs)
        self.capture(self.cur_item._objs[-1])

    def paint_path(self, *args, **kwargs):
        start = len(self.cur_item._objs)
        super().paint_path(*args, **kwargs)
        for obj in self.cur_item._objs[start:]:
            self.capture(obj, args[0] if args else kwargs.get("gstate"))


class TaggedInterpreter(PDFPageInterpreter):
    def do_BDC(self, tag, props):
        if isinstance(props, PSLiteral):
            props = dict_value(self.resources.get('Properties', {})).get(literal_name(props))
        super().do_BDC(tag, resolve1(props))

    def do_Do(self, xobjid):
        obj = self.xobjmap.get(literal_name(xobjid))
        stream = stream_value(obj) if obj is not None else None
        is_form = stream is not None and stream.get('Subtype') is not None and literal_name(stream.get('Subtype')) == 'Form'
        old_stream, old_marks = self.device.stream_id, self.device.marks[:]
        if is_form:
            self.device.stream_id = stream.objid or 0
        try:
            super().do_Do(xobjid)
        finally:
            self.device.stream_id, self.device.marks = old_stream, old_marks


def display_rect(rect, crop, rotation, size):
    """PDF user space -> rotated, cropped display points, including UserUnit scaling."""
    x0, y0, x1, y1 = crop
    points = []
    for x, y in ((rect[0], rect[1]), (rect[0], rect[3]), (rect[2], rect[1]), (rect[2], rect[3])):
        u, v = (x-x0)/(x1-x0), (y1-y)/(y1-y0)
        if rotation == 90:
            u, v = 1-v, u
        elif rotation == 180:
            u, v = 1-u, 1-v
        elif rotation == 270:
            u, v = v, 1-u
        points.append((u*size[0], v*size[1]))
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


class Document:
    def __init__(self, path, password=''):
        self.path = str(Path(path).resolve())
        self._password = password
        self.pdf = self.render_doc = self.source = None
        self.tags = []
        self._objects = []
        self.history = []
        self.dirty = False
        self.warnings = []
        self.cache = OrderedDict()
        self.form_locations = None
        try:
            self.pdf = pikepdf.open(self.path, password=password)
            self.render_doc = fitz.open(self.path)
            if self.render_doc.needs_pass and not self.render_doc.authenticate(password):
                raise ValueError('The password could not unlock the page renderer.')
            self.source = open(self.path, 'rb')
            self.miner = PDFDocument(PDFParser(self.source), password=password)
            self.miner_pages = list(PDFPage.create_pages(self.miner))
            self.page_count = len(self.pdf.pages)
            self.page_ids = {object_id(p.obj): i for i, p in enumerate(self.pdf.pages)}
            self.annotation_pages = {object_id(a): i for i, p in enumerate(self.pdf.pages)
                                     for a in p.obj.get('/Annots', []) if object_id(a)}
            self.crops = [tuple(float(v) for v in p.cropbox) for p in self.pdf.pages]
            self._parse()
        except Exception:
            self.close()
            raise

    def close(self):
        for resource in (self.source, self.render_doc, self.pdf):
            if resource is not None:
                resource.close()
        self.source = self.render_doc = self.pdf = None

    def _parse(self):
        root = self.pdf.Root.get('/StructTreeRoot')
        if not isinstance(root, pikepdf.Dictionary):
            self.warnings.append('This PDF has no structure tree. Its pages can still be viewed.')
            return
        rolemap = root.get('/RoleMap', {})
        # ParentTree is a useful fallback for tags whose /Pg was omitted.
        nums = {}
        stack = [root.get('/ParentTree')]
        seen = set()
        while stack:
            node = stack.pop()
            if not isinstance(node, pikepdf.Dictionary):
                continue
            oid = object_id(node)
            if oid and oid in seen:
                continue
            if oid:
                seen.add(oid)
            entries = node.get('/Nums', [])
            for i in range(0, len(entries)-1, 2):
                nums[int(entries[i])] = entries[i+1]
            stack.extend(node.get('/Kids', []))
        fallback = defaultdict(list)
        for page_no, page in enumerate(self.pdf.pages):
            key = page.obj.get('/StructParents')
            owners = nums.get(int(key)) if key is not None else None
            if isinstance(owners, pikepdf.Array):
                for mcid, owner in enumerate(owners):
                    if object_id(owner):
                        fallback[object_id(owner)].append(ContentRef(page_no, mcid))
        stack = [(child, None, None, 'StructTreeRoot', i) for i, child in reversed(list(enumerate(items(root.get('/K')))))]
        seen = set()
        while stack:
            obj, parent, inherited_page, path, index = stack.pop()
            if isinstance(obj, int):
                if parent is not None:
                    matches = [r for r in fallback.get(self._ids[parent], []) if r.mcid == obj]
                    self.tags[parent].refs.extend([ContentRef(inherited_page, obj)] if inherited_page is not None else matches or [ContentRef(None, obj)])
                continue
            if not isinstance(obj, pikepdf.Dictionary):
                continue
            page_no = self.page_ids.get(object_id(obj.get('/Pg')), inherited_page)
            kind = name(obj.get('/Type'))
            if kind in ('MCR', 'OBJR') or '/MCID' in obj:
                if parent is None:
                    continue
                if kind == 'OBJR':
                    target = obj.get('/Obj')
                    page_no = self.page_ids.get(object_id(target.get('/P')), page_no) if isinstance(target, pikepdf.Dictionary) else page_no
                    page_no = self.annotation_pages.get(object_id(target), page_no)
                    rect = target.get('/Rect') if isinstance(target, pikepdf.Dictionary) else None
                    self.tags[parent].refs.append(ContentRef(page_no, rect=tuple(map(float, rect)) if rect is not None else None))
                else:
                    mcid = obj.get('/MCID')
                    if mcid is not None:
                        stream = object_id(obj.get('/Stm'))
                        ref = ContentRef(page_no, int(mcid), stream[0] if stream else 0)
                        matches = [r for r in fallback.get(self._ids[parent], []) if r.mcid == int(mcid)]
                        self.tags[parent].refs.extend(matches if page_no is None and not stream and matches else [ref])
                continue
            oid = object_id(obj)
            if oid and oid in seen:
                self.warnings.append(f'Repeated or cyclic structure reference {oid} was skipped.')
                continue
            if oid:
                seen.add(oid)
            role = name(obj.get('/S')) or '(unspecified)'
            mapped, role_seen = role, set()
            namespace = obj.get('/NS')
            localmap = namespace.get('/RoleMapNS', {}) if isinstance(namespace, pikepdf.Dictionary) else {}
            while mapped not in role_seen:
                role_seen.add(mapped)
                value = localmap.get('/'+mapped, rolemap.get('/'+mapped))
                if value is None:
                    break
                mapped = name(value[0] if isinstance(value, pikepdf.Array) else value)
            tag_id = len(self.tags)
            tag = Tag(tag_id, parent, role, mapped, f'{path}/{role}[{index}]',
                      f'{oid[0]} {oid[1]} R' if oid else 'Direct object',
                      *[str(obj.get(k, '')) for k in ('/T', '/Alt', '/ActualText', '/Lang')],
                      str(obj.get('/A', '')))
            tag.expansion = str(obj.get('/E', ''))
            tag.identifier = str(obj.get('/ID', ''))
            tag.dictionary = describe_dictionary(obj)
            class_names = items(obj.get('/C'))
            classmap = root.get('/ClassMap', {})
            tag.classes = '\n'.join(f'{c}: {describe_dictionary(classmap.get(str(c))) if isinstance(classmap.get(str(c)), pikepdf.Dictionary) else describe_value(classmap.get(str(c)))}' for c in class_names if isinstance(c, pikepdf.Name))
            tag.inherited_language = tag.language or (self.tags[parent].inherited_language if parent is not None else str(self.pdf.Root.get('/Lang', '')))
            self.tags.append(tag)
            self._objects.append(obj)
            if not hasattr(self, '_ids'):
                self._ids = []
            self._ids.append(oid)
            if page_no is not None:
                tag.pages.add(page_no)
            if parent is not None:
                self.tags[parent].children.append(tag_id)
            stack.extend((child, tag_id, page_no, tag.path, i) for i, child in reversed(list(enumerate(items(obj.get('/K'))))))
        if any(r.page is None for tag in self.tags for r in tag.refs):
            form_locations = self._locate_forms()
            for tag, oid in zip(self.tags, self._ids):
                resolved = []
                for ref in tag.refs:
                    if ref.page is not None:
                        resolved.append(ref)
                        continue
                    found = []
                    for stream_id, (form, pages) in form_locations.items():
                        if ref.stream and ref.stream != stream_id:
                            continue
                        owner_key = form.get('/StructParents')
                        owners = nums.get(int(owner_key)) if owner_key is not None else None
                        owned = isinstance(owners, pikepdf.Array) and ref.mcid is not None and 0 <= ref.mcid < len(owners) and object_id(owners[ref.mcid]) == oid
                        if ref.stream == stream_id or (not ref.stream and owned):
                            found.extend(ContentRef(p, ref.mcid, stream_id) for p in pages)
                    resolved.extend(found or [ref])
                tag.refs = resolved
        for tag in reversed(self.tags):
            tag.end = max([tag.id+1] + [self.tags[c].end for c in tag.children])
            tag.pages.update(r.page for r in tag.refs if r.page is not None)
            for child in tag.children:
                tag.pages.update(self.tags[child].pages)
        unknown = sum(not t.pages for t in self.tags)
        if unknown:
            self.warnings.append(f'{unknown} tag(s) have no resolvable page association.')

    def _locate_forms(self):
        if self.form_locations is not None:
            return self.form_locations
        locations = {}
        for page_no, page in enumerate(self.pdf.pages):
            pending = [(page, page.resources)]
            seen = set()
            while pending:
                content, resources = pending.pop()
                try:
                    for operands, operator in pikepdf.parse_content_stream(content, operators='Do'):
                        if str(operator) != 'Do' or not operands:
                            continue
                        target = resources.get('/XObject', {}).get(str(operands[0]))
                        oid = object_id(target)
                        if not isinstance(target, pikepdf.Stream) or str(target.get('/Subtype')) != '/Form' or not oid:
                            continue
                        locations.setdefault(oid[0], (target, set()))[1].add(page_no)
                        if oid in seen:
                            continue
                        seen.add(oid)
                        pending.append((target, target.get('/Resources', resources)))
                except (pikepdf.PdfError, ValueError, TypeError):
                    self.warnings.append(f'Could not inspect some Form XObjects on page {page_no+1}.')
        self.form_locations = locations
        return locations

    def filter(self, query='', role='All tags', page=None, missing_alt=False):
        return [t.id for t in self.tags if t.matches(query, role, page, missing_alt)]

    def page_geometry(self, page_no):
        if page_no in self.cache:
            self.cache.move_to_end(page_no)
            return self.cache[page_no]
        manager = PDFResourceManager()
        device = TaggedDevice(manager)
        page = self.miner_pages[page_no]
        old_rotation = page.rotate
        page.rotate = 0
        try:
            TaggedInterpreter(manager, device).process_page(page)
        finally:
            page.rotate = old_rotation
            device.close()
        ox, oy = page.mediabox[:2]
        geometry = {key: [(r[0]+ox, r[1]+oy, r[2]+ox, r[3]+oy) for r in rects]
                    for key, rects in device.geometry.items()}
        result = (geometry, {key: ''.join(value) for key, value in device.text.items()}, {key: sorted(value) for key, value in device.colors.items()})
        self.cache[page_no] = result
        while len(self.cache) > 8:
            self.cache.popitem(last=False)
        return result

    def selection(self, tag_id, page_no):
        tag = self.tags[tag_id]
        refs = {r for node in self.tags[tag.id:tag.end] for r in node.refs if r.page == page_no}
        geometry, text, colors = self.page_geometry(page_no)
        boxes, chunks, unavailable = [], [], 0
        for ref in sorted(refs, key=lambda r: (r.stream, r.mcid if r.mcid is not None else -1, str(r.rect))):
            if ref.rect is not None:
                boxes.append(ref.rect)
            elif ref.mcid is not None:
                key = (ref.stream, ref.mcid)
                rects = geometry.get(key, [])
                if rects:
                    boxes.append((min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)))
                    if text.get(key):
                        chunks.append(text[key])
                else:
                    unavailable += 1
        page = self.render_doc[page_no]
        boxes = [display_rect(r, self.crops[page_no], page.rotation, (page.rect.width, page.rect.height)) for r in boxes]
        note = f'{len(boxes)} content outline(s) on this page.' if boxes else 'No content bounds available for this tag on this page.'
        if unavailable:
            note += f' {unavailable} marked-content reference(s) could not be located.'
        if any(r.page is None for node in self.tags[tag.id:tag.end] for r in node.refs):
            note += ' Some references have no known page.'
        color_lines = sorted({line for ref in refs for line in colors.get((ref.stream, ref.mcid), [])})
        color_info = '\n\n'.join(color_lines) or 'No color information could be resolved for this selection on this page.'
        return boxes, '\n'.join(chunks), note, color_info

    def render(self, page_no, scale):
        page = self.render_doc[page_no]
        # Bound memory for enormous page sizes / large zoom values.
        scale = min(scale, (20_000_000 / max(1, page.rect.width*page.rect.height)) ** .5)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.width, pix.height, pix.samples, scale

    def export(self, path, ids):
        rows = []
        for i in ids:
            tag = self.tags[i]
            rows.append(dict(id=i+1, tag=tag.role, mapped_role=tag.mapped_role,
                pages=', '.join(str(p+1) for p in sorted(tag.pages)), title=tag.title,
                alt_text=tag.alt, actual_text=tag.actual_text, language=tag.language,
                object=tag.object_ref, path=tag.path, attributes=tag.attributes, identifier=tag.identifier, expansion=tag.expansion, classes=tag.classes))
        if str(path).lower().endswith('.json'):
            Path(path).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
        else:
            columns = ['id','tag','mapped_role','pages','title','alt_text','actual_text','language','object','path','attributes','identifier','expansion','classes']
            with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    # Keep spreadsheet exports from interpreting PDF strings as formulas.
                    writer.writerow({k: "'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v for k, v in row.items()})

    def edit(self, tag_id, values):
        role = values['role'].strip().lstrip('/')
        if not role or any(c.isspace() or c in '/()<>[]{}%#' for c in role):
            raise ValueError('Enter a tag name without spaces or PDF delimiters, for example P, H1, TH, or Figure.')
        obj = self._objects[tag_id]
        keys = {'role': '/S', 'alt': '/Alt', 'actual_text': '/ActualText', 'title': '/T', 'language': '/Lang', 'expansion': '/E'}
        previous = {key: obj.get(key) for key in keys.values()}
        changed = False
        for field, key in keys.items():
            value = role if field == 'role' else values.get(field, str(obj.get(key, '')))
            new = pikepdf.Name('/'+value) if field == 'role' else pikepdf.String(value) if value else None
            if str(obj.get(key, '')) != str(new if new is not None else ''):
                changed = True
            if new is None:
                if key in obj:
                    del obj[key]
            else:
                obj[key] = new
        if changed:
            self.history.append((tag_id, previous))
            self.dirty = True
            self._refresh()
        return changed

    def _refresh(self):
        self.tags, self._objects, self._ids, self.warnings = [], [], [], []
        self._parse()

    def undo(self):
        if not self.history:
            return None
        tag_id, previous = self.history.pop()
        obj = self._objects[tag_id]
        for key, value in previous.items():
            if value is None:
                if key in obj:
                    del obj[key]
            else:
                obj[key] = value
        self.dirty = True
        self._refresh()
        return tag_id

    def save_copy(self, path):
        import os
        import tempfile
        target = Path(path).resolve()
        if target == Path(self.path) or (target.exists() and os.path.samefile(target, self.path)):
            raise ValueError('Choose a different filename to keep the original PDF intact.')
        fd, temporary = tempfile.mkstemp(prefix='.tag-inspector-', suffix='.pdf', dir=target.parent)
        os.close(fd)
        try:
            self.pdf.save(temporary, encryption=True if self.pdf.is_encrypted else None)
            with pikepdf.open(temporary, password=self._password) as check:
                if len(check.pages) != self.page_count:
                    raise ValueError('Saved PDF verification failed.')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.dirty = False
        return str(target)
