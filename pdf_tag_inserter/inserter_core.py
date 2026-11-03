"""Insert consecutive structure tags, with transactional undo and content ownership."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from io import BytesIO
import os
import tempfile
import re
import pikepdf as q
import pymupdf as fitz
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager
from content_geometry import TaggedDevice, TaggedInterpreter, display_rect


def kids(obj):
    value = obj.get('/K')
    return list(value) if isinstance(value, q.Array) else [] if value is None else [value]


def oid(obj):
    return tuple(obj.objgen) if isinstance(obj, q.Object) and obj.is_indirect else None


def same(a, b):
    return oid(a) == oid(b) if oid(a) and oid(b) else a == b


@dataclass
class Node:
    key: str
    obj: object
    parent: object
    slot: int
    label: str
    page: int | None
    structure: bool


@dataclass
class Content:
    label: str
    page: int
    mcid: int
    stream: int = 0
    owner: object = None
    slot: int = -1
    ref: object = None
    start: int | None = None
    end: int | None = None
    bounds: tuple | None = None
    text: str = ''


class Editor:
    def __init__(self, path, password=''):
        self.path = Path(path).resolve()
        self.password = password
        self.pdf = q.open(self.path, password=password)
        self.renderer = fitz.open(self.path)
        if self.renderer.needs_pass:
            self.renderer.authenticate(password)
        self.undo_data = []
        self.dirty = False
        self.version = 0
        self.reindex()

    def close(self):
        self.pdf.close()
        self.renderer.close()

    def reindex(self):
        self.root = self.pdf.Root.get('/StructTreeRoot')
        self.page_ids = {oid(p.obj): i for i,p in enumerate(self.pdf.pages)}
        self.nodes = {'root': Node('root', self.root, None, -1, 'Structure tree root', None, True)}
        self.order = []
        self.parents = {}
        pending = [(x,self.root,i,'root',None) for i,x in reversed(list(enumerate(kids(self.root))))] if self.root is not None else []
        seen = set()
        while pending:
            obj, parent, slot, parent_key, inherited_page = pending.pop()
            key = f'{parent_key}.{slot}'
            dictionary = isinstance(obj, q.Dictionary)
            page = self.page_ids.get(oid(obj.get('/Pg')), inherited_page) if dictionary else inherited_page
            structure = dictionary and '/S' in obj
            if structure:
                label = str(obj.S).lstrip('/')
                if oid(obj) in seen:
                    raise ValueError('The structure tree has repeated/cyclic tags; repair those references before inserting.')
                if oid(obj):
                    seen.add(oid(obj))
                title = str(obj.get('/T', obj.get('/Alt', ''))).replace('\n',' ')[:90]
                if title:
                    label += ' - '+title
            elif isinstance(obj,int):
                label = f'Content: MCID {obj}'
            elif dictionary:
                label = f'Content: {obj.get("/Type", "reference")} {obj.get("/MCID", "")}'
            else:
                label = 'Content reference'
            node = Node(key,obj,parent,slot,label,page,structure)
            self.nodes[key] = node
            self.parents[key] = parent_key
            self.order.append(key)
            if structure:
                pending.extend((x,obj,i,key,page) for i,x in reversed(list(enumerate(kids(obj)))))

    def snapshot(self):
        out = BytesIO()
        self.pdf.save(out, encryption=True if self.pdf.is_encrypted else None)
        return out.getvalue()

    def restore(self, data):
        new = q.open(BytesIO(data), password=self.password)
        self.pdf.close()
        self.pdf = new
        self.version += 1
        self.reindex()

    def destination(self, selected, position, child_index=1):
        node = self.nodes[selected]
        if position in ('Before selected', 'After selected'):
            if node.parent is None:
                raise ValueError('Select a tag or content item; the tree root has no siblings.')
            return node.parent, node.slot + (position == 'After selected')
        if not node.structure:
            raise ValueError('Choose a container tag for child insertion, or use Before/After.')
        parent = node.obj
        length = len(kids(parent)) if parent is not None else 0
        if position == 'First children':
            index = 0
        elif position == 'Last children':
            index = length
        else:
            index = int(child_index)-1
            if not 0 <= index <= length:
                raise ValueError(f'Child position must be between 1 and {length+1}, including content-reference items.')
        return parent, index

    def _number_tree(self):
        if '/ParentTree' not in self.root:
            self.root.ParentTree = q.NumberTree.new(self.pdf).obj
        return q.NumberTree(self.root.ParentTree)

    def _set_owner(self, content, tag):
        tree = self._number_tree()
        scope = content.ref.get('/Stm') if content.stream and isinstance(content.ref,q.Dictionary) else self.pdf.pages[content.page].obj
        key = scope.get('/StructParents')
        if key is None:
            key = max([int(k) for k in tree.keys()]+[-1])+1
            scope.StructParents = key
        existing = tree.get(int(key))
        if existing is not None and not isinstance(existing,q.Array):
            raise ValueError('The selected content has an invalid ParentTree entry.')
        owners = list(existing) if existing is not None else []
        current = owners[content.mcid] if content.mcid < len(owners) else None
        if current is not None and (content.owner is None or not same(current,content.owner)):
            raise ValueError('Content ownership is inconsistent in the ParentTree; no changes were kept.')
        owners.extend([None]*max(0,content.mcid+1-len(owners)))
        owners[content.mcid] = tag
        tree[int(key)] = q.Array(owners)
        self.root.ParentTreeNextKey = max(int(self.root.get('/ParentTreeNextKey',0)),int(key)+1)

    def _content_bytes(self, page_no, chosen):
        instructions = list(q.parse_content_stream(self.pdf.pages[page_no]))
        starts = {c.start:c for c in chosen if c.start is not None}
        ends = {c.end:c for c in chosen if c.end is not None}
        output = []
        for i, instruction in enumerate(instructions):
            if i in starts:
                output.append(([q.Name.Span,q.Dictionary(MCID=starts[i].mcid)], q.Operator('BDC')))
            output.append(instruction)
            if i in ends:
                output.append(([],q.Operator('EMC')))
        return q.unparse_content_stream(output)

    def scan_content(self, page_no):
        """List existing marked content and unmarked text/image/vector painting units."""
        page = self.pdf.pages[page_no]
        instructions = list(q.parse_content_stream(page))
        candidates = []
        present = set()
        depth, text_start = 0, None
        text_marked = False
        for i, instruction in enumerate(instructions):
            # Inline images are intentionally left intact, but cannot be picked here.
            if not hasattr(instruction,'operator'):
                continue
            operands, operator = instruction.operands, str(instruction.operator)
            if operator in ('BDC','BMC'):
                depth += 1
                if text_start is not None:
                    text_marked = True
                if operator == 'BDC' and len(operands)>1:
                    props=operands[1]
                    if isinstance(props,q.Name):
                        props=page.resources.get('/Properties',{}).get(str(props))
                    if isinstance(props,q.Dictionary) and '/MCID' in props:
                        present.add(int(props.MCID))
            elif operator == 'EMC':
                depth=max(0,depth-1)
            elif operator == 'BT':
                text_start, text_marked = i, depth>0
            elif operator == 'ET':
                if text_start is not None and not text_marked and depth==0:
                    candidates.append(('Text object',text_start,i))
                text_start=None
            elif depth==0 and text_start is None:
                if operator == 'Do':
                    target=page.resources.get('/XObject',{}).get(str(operands[0]))
                    if isinstance(target,q.Stream):
                        if str(target.get('/Subtype')) == '/Image':
                            candidates.append(('Image',i,i))
                        elif str(target.get('/Subtype')) == '/Form' and self._unmarked_form(target,set()):
                            candidates.append(('Form artwork',i,i))
                elif operator in ('S','s','f','F','f*','B','B*','b','b*'):
                    candidates.append(('Vector artwork',i,i))
        sources=[]
        used=set()
        for key in self.order:
            n=self.nodes[key]
            if n.structure or n.page!=page_no:
                continue
            obj=n.obj
            if isinstance(obj,int):
                mcid,stream=obj,0
            elif isinstance(obj,q.Dictionary) and '/MCID' in obj:
                mcid=int(obj.MCID)
                stream=oid(obj.get('/Stm'))
                stream=stream[0] if stream else 0
            else:
                continue
            pair=(stream,mcid)
            if pair in used:
                raise ValueError('Duplicate content ownership found on this page. Repair it before moving content.')
            used.add(pair)
            if not stream:
                present.add(mcid)
            sources.append(Content(f'Existing /{str(n.parent.get("/S", "tag")).lstrip("/")} MCID {mcid}',page_no,mcid,stream,n.parent,n.slot,obj))
        for mcid in sorted(present):
            if (0,mcid) not in used:
                # A ParentTree owner without a resolvable /K link cannot safely be reassigned.
                root=self.root
                pt=root.get('/ParentTree') if root is not None else None
                sp=page.obj.get('/StructParents')
                owners=q.NumberTree(pt).get(int(sp)) if pt is not None and sp is not None else None
                if isinstance(owners,q.Array) and mcid<len(owners) and owners[mcid] is not None:
                    continue
                sources.append(Content(f'Unassigned MCID {mcid}',page_no,mcid))
        sp=page.obj.get('/StructParents')
        pt=self.root.get('/ParentTree') if self.root is not None else None
        owners=q.NumberTree(pt).get(int(sp)) if pt is not None and sp is not None else None
        next_id=max(max(present,default=-1)+1,len(owners) if isinstance(owners,q.Array) else 0)
        for offset,(label,start,end) in enumerate(candidates):
            sources.append(Content('Untagged '+label,page_no,next_id+offset,start=start,end=end))
        # Analyze a temporary in-memory PDF with candidate MCIDs. Restore /Contents immediately.
        unmarked=[c for c in sources if c.start is not None]
        original=page.obj.get('/Contents')
        try:
            if unmarked:
                page.obj.Contents=self.pdf.make_stream(self._content_bytes(page_no,unmarked))
            data=self.snapshot()
        finally:
            if original is None:
                if '/Contents' in page.obj:
                    del page.obj.Contents
            else:
                page.obj.Contents=original
        miner=PDFDocument(PDFParser(BytesIO(data)),password=self.password)
        mp=next(p for i,p in enumerate(PDFPage.create_pages(miner)) if i==page_no)
        mp.rotate=0
        manager=PDFResourceManager()
        device=TaggedDevice(manager)
        TaggedInterpreter(manager,device).process_page(mp)
        ox,oy=mp.mediabox[:2]
        render_page=self.renderer[page_no]
        crop=tuple(map(float,page.cropbox))
        for c in sources:
            rectangles=device.geometry.get((c.stream,c.mcid),[])
            if rectangles:
                box=(min(r[0] for r in rectangles)+ox,min(r[1] for r in rectangles)+oy,max(r[2] for r in rectangles)+ox,max(r[3] for r in rectangles)+oy)
                c.bounds=display_rect(box,crop,render_page.rotation,(render_page.rect.width,render_page.rect.height))
            c.text=''.join(device.text.get((c.stream,c.mcid),[])).strip()
            if c.text:
                c.label+=' | '+c.text.replace('\n',' ')[:110]
        device.close()
        return sources

    def _unmarked_form(self, stream, seen):
        identity=oid(stream)
        if identity in seen:
            return False
        seen=seen|{identity}
        try:
            for operands,op in q.parse_content_stream(stream):
                if str(op) in ('BMC','BDC'):
                    return False
                if str(op)=='Do':
                    obj=stream.get('/Resources',{}).get('/XObject',{}).get(str(operands[0]))
                    if obj is None:
                        return False
                    if str(obj.get('/Subtype'))=='/Form' and not self._unmarked_form(obj,seen):
                        return False
        except (q.PdfError,ValueError,TypeError):
            return False
        return True

    def insert(self, selected, position, count, role, properties=None, sources=None, child_index=1, scan_version=None):
        role=role.strip().lstrip('/')
        if not re.fullmatch(r'[^\s/()<>\[\]{}%#\x00]+',role):
            raise ValueError('Enter a valid tag name, such as P, TD, TH, Span, or Figure.')
        count=int(count)
        if count<1:
            raise ValueError('Number of tags must be at least 1.')
        sources=list(sources or [])
        if sources and (len(sources)!=count or scan_version!=self.version):
            raise ValueError('Content mode creates one tag per selected content item. Rescan after any insertion or undo.')
        if len({(c.page,c.stream,c.mcid) for c in sources}) != len(sources):
            raise ValueError('Select each content item only once.')
        parent,index=self.destination(selected,position,child_index)
        before=self.snapshot()
        was_dirty=self.dirty
        try:
            if self.root is None:
                self.root=self.pdf.make_indirect(q.Dictionary(Type=q.Name.StructTreeRoot,K=q.Array()))
                self.pdf.Root.StructTreeRoot=self.root
                parent=self.root
            if not parent.is_indirect:
                raise ValueError('This PDF has a direct container dictionary. Repair it to an indirect structure element before inserting.')
            original=kids(parent)
            # A selected content item can be removed from this same parent; retain the insertion boundary.
            remove_slots={}
            for c in sources:
                if c.owner is not None:
                    if not c.owner.is_indirect:
                        raise ValueError('The content owner is a direct dictionary; repair it before moving its content.')
                    k=oid(c.owner)
                    remove_slots.setdefault(k,(c.owner,set()))[1].add(c.slot)
            index-=sum(1 for c in sources if c.owner is not None and same(c.owner,parent) and c.slot<index)
            for owner,slots in remove_slots.values():
                owner.K=q.Array([x for i,x in enumerate(kids(owner)) if i not in slots])
            for page_no in sorted({c.page for c in sources if c.start is not None}):
                self.pdf.pages[page_no].obj.Contents=self.pdf.make_stream(self._content_bytes(page_no,[c for c in sources if c.page==page_no]))
            created=[]
            mapping={'title':'/T','alt':'/Alt','actual':'/ActualText','language':'/Lang','expansion':'/E'}
            for i in range(count):
                tag=self.pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name('/'+role),P=parent,K=q.Array()))
                for field,value in (properties or {}).items():
                    if field in mapping and value:
                        tag[mapping[field]]=q.String(value.replace('{n}',str(i+1)))
                if sources:
                    content=sources[i]
                    ref=q.Dictionary(Type=q.Name.MCR,Pg=self.pdf.pages[content.page].obj,MCID=content.mcid)
                    if content.stream:
                        ref.Stm=content.ref.Stm
                    tag.Pg=self.pdf.pages[content.page].obj
                    tag.K=ref
                    self._set_owner(content,tag)
                created.append(tag)
            existing=kids(parent)
            parent.K=q.Array(existing[:index]+created+existing[index:])
            mark=self.pdf.Root.get('/MarkInfo',q.Dictionary())
            mark.Marked=True
            self.pdf.Root.MarkInfo=mark
            self.version+=1
            self.reindex()
        except Exception:
            self.restore(before)
            self.dirty=was_dirty
            raise
        self.undo_data.append(before)
        self.dirty=True
        ids={oid(t) for t in created}
        return [k for k in self.order if oid(self.nodes[k].obj) in ids]

    def undo(self):
        if self.undo_data:
            self.restore(self.undo_data.pop())
            self.dirty=True

    def save(self, path):
        target=Path(path).resolve()
        if target==self.path or (target.exists() and os.path.samefile(target,self.path)):
            raise ValueError('Choose a new filename; the original PDF is kept intact.')
        fd,temp=tempfile.mkstemp(prefix='.tag-insert-',suffix='.pdf',dir=target.parent)
        os.close(fd)
        try:
            self.pdf.save(temp,encryption=True if self.pdf.is_encrypted else None)
            with q.open(temp,password=self.password) as check:
                if len(check.pages)!=len(self.pdf.pages):
                    raise ValueError('Saved PDF verification failed.')
            os.replace(temp,target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.dirty=False
