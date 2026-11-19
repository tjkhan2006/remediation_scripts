"""Conservative transfer of page-stream tag boundaries onto equivalent original artwork."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from io import BytesIO
import os
import tempfile
import pikepdf as q
import pymupdf as fitz
from content_match import geometry_plan, records, near

# Load the inspector under a unique name; keep sibling tools untouched.
spec = importlib.util.spec_from_file_location('transfer_inspector_engine', Path(__file__).resolve().parents[1] / 'pdf_tag_inspector' / 'engine.py')
inspector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = inspector
spec.loader.exec_module(inspector)
Document = inspector.Document


def clean_value(value, depth=0, *, pdf=None, path='metadata'):
    """Rebuild metadata, including streams, without importing source document links.

    Stream bytes stay encoded; Filter/DecodeParms are copied with the dictionary.
    This supports valid stream attribute objects without decoding or changing them.
    """
    if depth > 24:
        raise ValueError(f'{path}: metadata is cyclic or too deeply nested')
    if isinstance(value, (q.Dictionary, q.Stream)):
        kind = str(value.get('/Type', ''))
        if kind in ('/Catalog', '/Pages', '/Page', '/StructTreeRoot', '/StructElem', '/MCR', '/OBJR'):
            raise ValueError(f'{path}: metadata refers to document structure ({kind}); cannot copy it as metadata')
        if any(k in value for k in ('/ParentTree', '/StructParents', '/StructParent', '/Pg')):
            raise ValueError(f'{path}: metadata contains a document/content association that needs review')
        if isinstance(value, q.Stream):
            if pdf is None:
                raise ValueError(f'{path}: a destination PDF is required to copy a metadata stream')
            result = pdf.make_stream(value.read_raw_bytes())
        else:
            result = q.Dictionary()
        for key, child in value.items():
            if isinstance(value, q.Stream) and str(key) == '/Length':
                continue  # pikepdf computes the new stream length on serialization.
            result[str(key)] = clean_value(child, depth+1, pdf=pdf, path=path+str(key))
        return result
    if isinstance(value, q.Array):
        return q.Array([clean_value(v, depth+1, pdf=pdf, path=f'{path}[{i}]') for i,v in enumerate(value)])
    if isinstance(value, q.Name): return q.Name(str(value))
    if isinstance(value, q.String): return q.String(bytes(value))
    return value


def stream_parts(page):
    drawing, events, stack = [], [], []
    for inst in q.parse_content_stream(page):
        op = str(inst.operator) if hasattr(inst, 'operator') else ''
        if op in ('BMC', 'BDC'):
            props = inst.operands[1] if op == 'BDC' else None
            if isinstance(props, q.Name):
                props = page.resources.get('/Properties', {}).get(str(props))
            mcid = int(props.MCID) if isinstance(props, q.Dictionary) and '/MCID' in props else None
            marker = (str(inst.operands[0]), mcid)
            stack.append(marker)
            events.append((len(drawing), True, marker))
        elif op == 'EMC':
            if not stack: raise ValueError('Unbalanced marked content')
            events.append((len(drawing), False, stack.pop()))
        else:
            drawing.append(inst)
    if stack: raise ValueError('Unbalanced marked content')
    return drawing, events



class Transfer:
    def __init__(self, original, source):
        self.original = Path(original).resolve()
        self.source = Path(source).resolve()
        self.reference = Document(self.source)
        try:
            self.base = Document(self.original)
            self.pdf = q.open(self.original)
            if len(self.base.pdf.pages) != len(self.reference.pdf.pages):
                raise ValueError('Page counts differ; page mapping is required before transfer.')
            if any(t.refs and any(r.stream or r.rect is not None for r in t.refs) for t in self.reference.tags):
                self.notice = 'Form/annotation references need content matching. Open Show issues for any unresolved content.'
            else: self.notice = ''
            self.states = ['Pending'] * len(self.pdf.pages)
            self.messages = [''] * len(self.pdf.pages)
            self.done = set()
            self.history = []
            self._source_record_cache = {}
            self._initialize()
        except Exception:
            self.close()
            raise

    def _initialize(self):
        # Starting with an already tagged base would leave stale Form/annotation ownership.
        if '/StructTreeRoot' in self.base.pdf.Root or self.base.tags or any('/StructParents' in p.obj for p in self.pdf.pages):
            raise ValueError('Choose an original without a structure tree or page StructParents.')
        self.root = self.pdf.make_indirect(q.Dictionary(Type=q.Name.StructTreeRoot))
        self.pdf.Root.StructTreeRoot = self.root
        self.pdf.Root.MarkInfo = q.Dictionary(Marked=True)
        source_root = self.reference.pdf.Root.get('/StructTreeRoot')
        if source_root is None: raise ValueError('Reference PDF has no structure tree.')
        if any('Repeated or cyclic' in w for w in self.reference.warnings):
            raise ValueError('Cyclic/shared source hierarchy requires review before transfer.')
        if any(inspector.object_id(o) is None for o in self.reference._objects):
            raise ValueError('Direct source structure elements require normalization before transfer.')
        if self.reference.warnings:
            self.notice += ' Source parser warnings: ' + '; '.join(self.reference.warnings)
        for key in ('/RoleMap', '/ClassMap'):
            if key in source_root: self.root[key] = clean_value(source_root[key], pdf=self.pdf, path='StructTreeRoot'+key)
        if '/Lang' in self.reference.pdf.Root:
            self.pdf.Root.Lang = clean_value(self.reference.pdf.Root.Lang, pdf=self.pdf, path='Catalog/Lang')
        self.nodes = []
        for tag, obj in zip(self.reference.tags, self.reference._objects):
            node = self.pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem, S=q.Name('/'+tag.role)))
            for key in ('/T','/Alt','/ActualText','/Lang','/E','/A','/C','/ID'):
                if key in obj: node[key] = clean_value(obj[key], pdf=self.pdf, path=tag.path+key)
            node.P = self.root if tag.parent is None else self.nodes[tag.parent]
            self.nodes.append(node)
        self._copy_relationships(source_root)
        self._refresh_tree()

    def _copy_relationships(self, source_root):
        """Allocate namespace/tag targets first, then reconnect foreign references."""
        self.relationship_issues = []
        namespaces = {}
        namespace_list = []

        def namespace(value, path):
            if not isinstance(value, q.Dictionary):
                raise ValueError(f'{path}: expected a namespace dictionary')
            if str(value.get('/Type', '/Namespace')) != '/Namespace':
                raise ValueError(f'{path}: expected a Namespace, found another object type')
            if not isinstance(value.get('/NS'), q.String):
                raise ValueError(f'{path}: namespace URI /NS must be a text string')
            key = inspector.object_id(value) or ('direct', id(value))
            if key in namespaces: return namespaces[key]
            result = self.pdf.make_indirect(q.Dictionary(Type=q.Name.Namespace))
            namespaces[key] = result
            namespace_list.append(result)
            # Register the shell before following RoleMapNS: namespace maps may
            # legitimately point back to each other without copying page graphs.
            for name, child in value.items():
                if str(name) != '/RoleMapNS':
                    result[str(name)] = clean_value(child, pdf=self.pdf, path=path+str(name))
            if '/RoleMapNS' in value:
                mapping = value.RoleMapNS
                if not isinstance(mapping, q.Dictionary):
                    raise ValueError(f'{path}/RoleMapNS: expected a dictionary')
                remapped = q.Dictionary()
                for role, target in mapping.items():
                    where = path+'/RoleMapNS'+str(role)
                    if isinstance(target, q.Name):
                        remapped[str(role)] = q.Name(str(target))
                    elif isinstance(target, q.Array) and len(target)==2 and isinstance(target[0], q.Name):
                        remapped[str(role)] = q.Array([q.Name(str(target[0])), namespace(target[1], where+'[1]')])
                    else:
                        raise ValueError(f'{where}: expected a role name or [role, namespace]')
                result.RoleMapNS = remapped
            return result

        if '/Namespaces' in source_root:
            if not isinstance(source_root.Namespaces, q.Array):
                raise ValueError('StructTreeRoot/Namespaces: expected an array')
            for i,value in enumerate(source_root.Namespaces):
                namespace(value, f'StructTreeRoot/Namespaces[{i}]')
        targets = {inspector.object_id(obj):node for obj,node in zip(self.reference._objects,self.nodes)}
        for tag,obj,node in zip(self.reference.tags,self.reference._objects,self.nodes):
            if '/NS' in obj: node.NS = namespace(obj.NS, tag.path+'/NS')
            if '/Ref' in obj:
                if not isinstance(obj.Ref, q.Array):
                    raise ValueError(f'{tag.path}/Ref: expected an array of tag references')
                refs = []
                for i,ref in enumerate(obj.Ref):
                    target = targets.get(inspector.object_id(ref))
                    if target is None:
                        self.relationship_issues.append({
                            'tag':tag.id, 'path':tag.path+f'/Ref[{i}]',
                            'source_object':list(inspector.object_id(ref)) if inspector.object_id(ref) else None,
                            'reason':'Target is outside the recovered tag tree',
                            'output_action':'Reference omitted; target not imported or guessed',
                        })
                        continue
                    refs.append(target)
                if refs or len(obj.Ref)==0: node.Ref = q.Array(refs)
        if namespace_list: self.root.Namespaces = q.Array(namespace_list)
        required = '2.0' if namespace_list else '1.5' if any('/Ref' in o for o in self.reference._objects) else '1.0'
        self.minimum_version = max((self.pdf.pdf_version, self.reference.pdf.pdf_version, required), key=lambda v: tuple(map(int,v.split('.'))))

    def _refresh_tree(self):
        by_id = {inspector.object_id(o): i for i,o in enumerate(self.reference._objects) if inspector.object_id(o)}
        by_direct = {id(o): i for i,o in enumerate(self.reference._objects)}
        def rebuild(value, page=None, owner=None):
            out = []
            for obj in inspector.items(value):
                if isinstance(obj, int):
                    pages = [page] if page is not None else [r.page for r in self.reference.tags[owner].refs if r.mcid == obj and not r.stream] if owner is not None else []
                    for pg in pages:
                        if (pg,obj) in self.links: out.extend(inspector.items(self.links[pg,obj]))
                elif isinstance(obj, q.Dictionary):
                    pg = self.reference.page_ids.get(inspector.object_id(obj.get('/Pg')), page)
                    kind = str(obj.get('/Type',''))
                    if '/MCID' in obj or kind == '/MCR':
                        mcid=int(obj.get('/MCID',-1))
                        stream = inspector.object_id(obj.get('/Stm'))
                        stream = stream[0] if stream else 0
                        pages=[pg] if pg is not None else [r.page for r in self.reference.tags[owner].refs if r.mcid==mcid and r.stream==stream] if owner is not None else []
                        for p in pages:
                            key = (p,stream,mcid) if stream else (p,mcid)
                            if key in self.links: out.extend(inspector.items(self.links[key]))
                    elif kind != '/OBJR':
                        idx = by_id.get(inspector.object_id(obj)) if inspector.object_id(obj) else by_direct.get(id(obj))
                        if idx is None: continue
                        node = self.nodes[idx]
                        node.K = q.Array(rebuild(obj.get('/K'), pg, idx))
                        out.append(node)
            return out
        if not hasattr(self, 'links'): self.links = {}
        self.root.K = q.Array(rebuild(self.reference.pdf.Root.StructTreeRoot.get('/K')))
        ids = sorted(((bytes(n.ID),n) for n in self.nodes if '/ID' in n), key=lambda pair:pair[0])
        if len({k for k,n in ids}) != len(ids): raise ValueError('Duplicate source tag IDs require review.')
        if ids: self.root.IDTree = self.pdf.make_indirect(q.Dictionary(Names=q.Array([v for k,n in ids for v in (q.String(k),n)])))

    def analyze_page(self, page):
        a,b = self.base.render_doc[page], self.reference.render_doc[page]
        if tuple(a.rect) != tuple(b.rect) or a.rotation != b.rotation:
            raise ValueError('Page dimensions or rotation differ')
        original_page=self.base.pdf.pages[page];source_page=self.reference.pdf.pages[page]
        for box in ('mediabox','cropbox'):
            left=tuple(map(float,getattr(original_page,box)));right=tuple(map(float,getattr(source_page,box)))
            if any(abs(x-y)>1e-6 for x,y in zip(left,right)):
                raise ValueError('Page coordinate systems differ')
        if float(original_page.obj.get('/UserUnit',1))!=float(source_page.obj.get('/UserUnit',1)):
            raise ValueError('Page coordinate systems differ')
        if a.get_text() != b.get_text(): raise ValueError('Page text differs')
        pa,pb = a.get_pixmap(),b.get_pixmap()
        if pa.samples != pb.samples: raise ValueError('Rendered page differs')
        drawing,_ = stream_parts(self.pdf.pages[page])
        other,events = stream_parts(self.reference.pdf.pages[page])
        if q.unparse_content_stream(drawing) != q.unparse_content_stream(other):
            raise ValueError('Drawing instructions differ; content matching needs manual review')
        # Nested/reused Forms can carry tagging outside page streams. Refuse affected pages.
        def forms(resources, seen):
            for obj in resources.get('/XObject',{}).values():
                if str(obj.get('/Subtype')) != '/Form': continue
                oid = inspector.object_id(obj)
                if oid in seen: continue
                seen.add(oid)
                if '/StructParents' in obj: raise ValueError('Tagged Form content needs review')
                if any(str(i.operator) in ('BDC','BMC') for i in q.parse_content_stream(obj) if hasattr(i,'operator')):
                    raise ValueError('Marked Form content needs review')
                forms(obj.get('/Resources',{}),seen)
        forms(self.pdf.pages[page].resources,set())
        forms(self.reference.pdf.pages[page].resources,set())
        owners = {}
        for tag in self.reference.tags:
            for ref in tag.refs:
                if ref.page == page and ref.mcid is not None and not ref.stream:
                    if ref.mcid in owners: raise ValueError('Duplicate source content ownership')
                    owners[ref.mcid] = tag.id
        active = []
        for pos,start,marker in events:
            role,mcid = marker
            if start:
                if mcid is not None and (role == '/Artifact' or any(r == '/Artifact' or m is not None for r,m in active)):
                    raise ValueError('Nested MCIDs or tagged artifacts require review')
                if mcid is None and role != '/Artifact':
                    raise ValueError('Non-MCID marked content requires review')
                active.append(marker)
            else: active.pop()
        occurrences = [m[1] for pos,start,m in events if start and m[1] is not None]
        if len(occurrences) != len(set(occurrences)): raise ValueError('Repeated source MCID')
        if any(m not in occurrences for m in owners): raise ValueError('Source tag refers to missing content')
        return drawing, events, owners

    @staticmethod
    def ref_key(ref):
        return (ref.page,ref.stream,ref.mcid) if ref.stream else (ref.page,ref.mcid)

    def linked(self, ref):
        return ref.mcid is not None and bool(self.links.get(self.ref_key(ref)))

    def source_records(self,page):
        if page not in self._source_record_cache:
            self._source_record_cache[page]=records(inspector,self.reference.miner_pages[page])
        return self._source_record_cache[page]

    def content_summary(self):
        refs=[r for t in self.reference.tags for r in t.refs]
        linked=sum(self.linked(r) for r in refs)
        return {'source_content_references':len(refs),'linked_content_references':linked,
                'unresolved_content_references':len(refs)-linked,
                'populated_tags':sum(any(self.linked(r) for r in t.refs) for t in self.reference.tags),
                'source_tags_with_content':sum(bool(t.refs) for t in self.reference.tags),
                'empty_source_leaves':sum(not t.refs and not t.children for t in self.reference.tags),
                'pages_needing_review':sum(v=='Needs review' for v in self.states)}

    def _parent_tree(self):
        nums=[]
        for page in sorted(self.done):
            refs={}
            for tag in self.reference.tags:
                for ref in tag.refs:
                    if ref.page==page and self.linked(ref):
                        for value in inspector.items(self.links[self.ref_key(ref)]):refs[int(value.MCID)]=self.nodes[tag.id]
            if refs:nums.extend([page,q.Array([refs.get(i) for i in range(max(refs)+1)])])
        self.root.ParentTree=self.pdf.make_indirect(q.Dictionary(Nums=q.Array(nums)))
        self.root.ParentTreeNextKey=len(self.pdf.pages)

    def verify_content(self,path,pages=None):
        """Independently reopen the PDF and check its actual content, K and ParentTree."""
        output=Document(path)
        try:
            if len(output.tags)!=len(self.reference.tags):raise ValueError('Output tag tree changed during save')
            parenttree=q.NumberTree(output.pdf.Root.StructTreeRoot.ParentTree) if '/ParentTree' in output.pdf.Root.StructTreeRoot else {}
            cache={}
            for tag,actual in zip(self.reference.tags,output.tags):
                relevant=[r for r in tag.refs if self.linked(r) and (pages is None or r.page in pages)]
                expected_count=sum(len(inspector.items(self.links[self.ref_key(r)])) for r in relevant)
                actual_refs=[r for r in actual.refs if pages is None or r.page in pages]
                if len(actual_refs)!=expected_count:raise ValueError(f'{tag.path}: saved tag content references are missing or unexpected')
                for page in {r.page for r in relevant}:
                    if page not in cache:cache[page]=records(inspector,output.miner_pages[page])
                    expected=[item for r in relevant if r.page==page for item in self.source_records(page).get((r.stream,r.mcid),[])]
                    found=[]
                    for ref in actual_refs:
                        if ref.page!=page:continue
                        if ref.mcid is None or ref.stream:raise ValueError(f'{tag.path}: unexpected output content scope')
                        found.extend(cache[page].get((0,ref.mcid),[]))
                        pg=output.pdf.pages[page].obj;key=pg.get('/StructParents')
                        owners=parenttree.get(int(key)) if key is not None else None
                        if owners is None or ref.mcid>=len(owners) or inspector.object_id(owners[ref.mcid])!=inspector.object_id(output._objects[actual.id]):
                            raise ValueError(f'{tag.path}: saved ParentTree does not own its page content')
                    if not expected:raise ValueError(f'{tag.path}: source has a content reference but no locatable glyph/image/path')
                    if ''.join(r[1] for r in expected)!=''.join(r[1] for r in found):raise ValueError(f'{tag.path}: saved tag text does not match source content')
                    remaining=list(found)
                    for item in expected:
                        index=next((i for i,other in enumerate(remaining) if near(item,other)),None)
                        if index is None:raise ValueError(f'{tag.path}: saved tag is missing original text/image/vector content')
                        remaining.pop(index)
                    if remaining:raise ValueError(f'{tag.path}: saved tag includes extra content')
        finally:output.close()

    def step(self):
        page=next((i for i,state in enumerate(self.states) if state=='Pending'),None)
        if page is None:return None
        refs=[r for t in self.reference.tags for r in t.refs if r.page==page]
        if not refs:
            self.states[page]='No source content'
            self.messages[page]='No source content references on this page; no content transferred.'
            return page
        pg=self.pdf.pages[page].obj
        before=(pg.get('/Contents'),pg.get('/StructParents'),dict(self.links),set(self.done),len(self.history),self.root.get('/ParentTree'),self.root.get('/ParentTreeNextKey'))
        try:
            mode='exact boundaries'
            try:drawing,events,owners=self.analyze_page(page)
            except ValueError as exc:
                reason=str(exc)
                has_form_refs=any(r.stream for r in refs)
                if 'Drawing instructions differ' not in reason and not (has_form_refs and ('Form content' in reason)):
                    raise
                # Geometry is used only after appearance/text/coordinate checks passed.
                data,mapping=geometry_plan(self,page,inspector);mode='text/image/position matching'
            else:
                out=[];at={};mapping={};next_id=0
                for pos,start,marker in events:at.setdefault(pos,[]).append((start,marker))
                for pos in range(len(drawing)+1):
                    for start,(role,old) in at.get(pos,[]):
                        if old in owners:
                            if start:
                                mapping[(page,old)]=[next_id];next_id+=1
                                out.append(([q.Name('/'+self.reference.tags[owners[old]].role),q.Dictionary(MCID=mapping[page,old][0])],q.Operator('BDC')))
                            else:out.append(([],q.Operator('EMC')))
                        elif role=='/Artifact':out.append(([q.Name.Artifact],q.Operator('BMC')) if start else ([],q.Operator('EMC')))
                    if pos<len(drawing):out.append(drawing[pos])
                data=q.unparse_content_stream(out)
            if not mapping:raise ValueError('No original content could be linked to this page’s source tags')
            pg.Contents=self.pdf.make_stream(data);pg.StructParents=page
            for key,mcids in mapping.items():
                self.links[key]=q.Array([q.Dictionary(Type=q.Name.MCR,Pg=pg,MCID=mcid) for mcid in mcids])
            self.done.add(page);self._refresh_tree();self._parent_tree()
            # Verify serialized data, not just our in-memory mapping or tree counts.
            with tempfile.TemporaryDirectory(prefix='tag_transfer_check_') as directory:
                path=Path(directory)/'check.pdf';path.write_bytes(self.snapshot())
                with fitz.open(path) as result:
                    base=self.base.render_doc[page]
                    if result[page].get_pixmap().samples!=base.get_pixmap().samples or result[page].get_text()!=base.get_text():raise ValueError('Content tagging changed page appearance or text')
                self.verify_content(path,{page})
            remaining=sum(not self.linked(r) for r in refs)
            self.states[page]='Partial' if remaining else 'Transferred'
            self.messages[page]=f'{len(mapping)} content regions linked and verified using {mode}; {remaining} unresolved.'
            self.history.append((page,before[0]))
        except Exception as exc:
            contents,sp,links,done,length,pt,nextkey=before
            if contents is not None:pg.Contents=contents
            elif '/Contents' in pg:del pg.Contents
            if sp is not None:pg.StructParents=sp
            elif '/StructParents' in pg:del pg.StructParents
            self.links=links;self.done=done;del self.history[length:]
            self._refresh_tree()
            for key,value in (('/ParentTree',pt),('/ParentTreeNextKey',nextkey)):
                if value is None:
                    if key in self.root:del self.root[key]
                else:self.root[key]=value
            self.states[page]='Needs review';self.messages[page]=str(exc)
        return page

    def undo(self):
        # Replay completed pages avoids retaining one full document snapshot per batch.
        if not self.history: return
        last = self.history[-1][0]
        completed = [p for p,_ in self.history[:-1]]
        self.pdf.close(); self.pdf=q.open(self.original)
        self.links={}; self.done=set(); self.history=[]
        self.states=['Pending']*len(self.pdf.pages); self.messages=['']*len(self.pdf.pages)
        self._initialize()
        for p in completed:
            for i in range(p):
                if self.states[i]=='Pending': self.states[i]='Needs review'
            self.step()
        return last

    def snapshot(self):
        buf=BytesIO(); self.pdf.save(buf, min_version=self.minimum_version); return buf.getvalue()

    def unresolved(self):
        return [(t.id,r) for t in self.reference.tags for r in t.refs if not self.linked(r)]

    def save(self,path, *, allow_unresolved_relationships=False, allow_unresolved_content=False):
        if self.reference.tags and not self.links:
            raise ValueError('No tag content has been linked. The output would contain an empty tag tree. See page issues before saving.')
        if (self.unresolved() or any(s in ('Pending','Needs review','Partial') for s in self.states)) and not allow_unresolved_content:
            raise ValueError('Tag content transfer is incomplete; explicit partial-save confirmation is required')
        if self.relationship_issues and not allow_unresolved_relationships:
            raise ValueError(f'{len(self.relationship_issues)} unresolved tag cross-references require explicit partial-save confirmation')
        target=Path(path).resolve()
        if target in (self.original,self.source) or any(target.exists() and os.path.samefile(target,p) for p in (self.original,self.source)):
            raise ValueError('Save to a separate output PDF')
        fd,tmp=tempfile.mkstemp(suffix='.pdf',dir=target.parent); os.close(fd)
        try:
            self.pdf.save(tmp, min_version=self.minimum_version)
            with q.open(tmp) as check:
                issues=check.check_pdf_syntax()
                if issues: raise ValueError('Output syntax check reported: '+'; '.join(issues))
            with fitz.open(tmp) as result:
                for i,page in enumerate(result):
                    base=self.base.render_doc[i]
                    if page.get_pixmap().samples != base.get_pixmap().samples or page.get_text()!=base.get_text():
                        raise ValueError(f'Output appearance/text changed on page {i+1}')
            self.verify_content(tmp)
            os.replace(tmp,target)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def close(self):
        for attr in ('reference','base','pdf'):
            obj=getattr(self,attr,None)
            if obj is not None: obj.close()
