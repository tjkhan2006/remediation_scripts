"""Match actual painted content when PDF editing has rewritten page operators."""
from collections import defaultdict
from io import BytesIO
import hashlib
import pikepdf as q
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdftypes import resolve1
from pdfminer.cmapdb import IdentityCMap, IdentityCMapByte


def glyph_bytes(font, data):
    if not font.is_multibyte(): return [data[i:i+1] for i in range(len(data))]
    cmap = font.cmap
    if isinstance(cmap, IdentityCMap):
        size = 1 if isinstance(cmap, IdentityCMapByte) else 2
        if len(data)%size: raise ValueError('Incomplete encoded text character')
        return [data[i:i+size] for i in range(0,len(data),size)]
    tree = getattr(cmap,'code2cid',None)
    if tree is None: raise ValueError('Font encoding cannot be split safely for content matching')
    result=[];start=0;node=tree
    for i,b in enumerate(data):
        node=node.get(b) if isinstance(node,dict) else None
        if node is None: raise ValueError('Unmapped encoded text character')
        if isinstance(node,int): result.append(data[start:i+1]); start=i+1; node=tree
    if start!=len(data): raise ValueError('Incomplete multibyte text character')
    return result


def normalize(document, page, instructions):
    """Split Tj/TJ into encoded glyphs while retaining spacing and all drawing state."""
    manager=PDFResourceManager();resources=resolve1(document.miner_pages[page].resources)
    fonts={}
    for name,spec in resolve1(resources.get('Font',{})).items():
        fonts[str(name)]=manager.get_font(getattr(spec,'objid',None),resolve1(spec))
    out=[];font=None;stack=[];marks=[];artifact_at={}
    def add(operands,op):
        idx=len(out);out.append((operands,q.Operator(op)))
        if any(m=='/Artifact' for m in marks):artifact_at[idx]=True
    def show(data):
        if font is None: raise ValueError('Text has no resolvable font')
        for part in glyph_bytes(font,bytes(data)):add([q.String(part)],'Tj')
    for inst in instructions:
        if not hasattr(inst,'operator'):
            idx=len(out);out.append(inst)
            if '/Artifact' in marks: artifact_at[idx]=True
            continue
        op=str(inst.operator);args=list(inst.operands)
        if op in ('BDC','BMC'):marks.append(str(args[0]));continue
        if op=='EMC':
            if not marks:raise ValueError('Unbalanced original marked content')
            marks.pop();continue
        if op=='Tf':font=fonts.get(str(args[0]).lstrip('/'))
        if op=='q':stack.append(font)
        if op=='Q' and stack:font=stack.pop()
        if op=='Tj':show(args[0])
        elif op=='TJ':
            for part in args[0]:
                if isinstance(part,q.String):show(part)
                else:add([q.Array([part])],'TJ')
        elif op=="'":add([],'T*');show(args[0])
        elif op=='"':add([args[0]],'Tw');add([args[1]],'Tc');add([],'T*');show(args[2])
        else:add(args,op)
    return out,artifact_at


def records(engine, miner_page):
    """Record each glyph/image/path with its scoped MCID and actual position."""
    class Device(engine.TaggedDevice):
        def __init__(self,manager):super().__init__(manager);self.records=defaultdict(list)
        def capture(self,obj,gstate=None):
            # Avoid collecting color/geometry twice; only the primitives are needed here.
            kind=type(obj).__name__;text=obj.get_text() if hasattr(obj,'get_text') else ''
            digest=''
            if hasattr(obj,'stream'):digest=hashlib.sha256(obj.stream.get_data()).hexdigest()
            item=(kind,text,tuple(float(v) for v in obj.bbox),digest)
            for key in set(k for k in self.marks if k is not None):self.records[key].append(item)
    manager=PDFResourceManager();device=Device(manager)
    old=miner_page.rotate;miner_page.rotate=0
    try:engine.TaggedInterpreter(manager,device).process_page(miner_page)
    finally:miner_page.rotate=old;device.close()
    return dict(device.records)


def near(a,b):
    return a[:2]==b[:2] and a[3]==b[3] and all(abs(x-y)<=0.1 for x,y in zip(a[2],b[2]))


def locate_records(expected, available):
    """Return unique primitive matches; repeated or ambiguous artwork needs review."""
    buckets=defaultdict(list)
    for key,record in available:
        b=record[2];buckets[(record[0],record[1],round(b[0]*2),round(b[1]*2))].append((key,record))
    used=set();answer=[]
    for record in expected:
        b=record[2];x,y=round(b[0]*2),round(b[1]*2);matches=[]
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                matches.extend(key for key,other in buckets.get((record[0],record[1],x+dx,y+dy),[]) if key not in used and near(record,other))
        if len(matches)!=1:raise ValueError('Content has no unique text/image/position match in the original PDF')
        used.add(matches[0]);answer.append(matches[0])
    return answer


def geometry_plan(session,page,engine):
    """Return rewritten original instructions and source-key -> output MCID lists."""
    original=session.pdf.pages[page]
    drawing,artifacts=normalize(session.base,page,list(q.parse_content_stream(original)))
    candidates=[]
    for i,inst in enumerate(drawing):
        op=str(inst[1]) if isinstance(inst,tuple) else str(inst.operator) if hasattr(inst,'operator') else 'INLINE IMAGE'
        if op in ('Tj','Do','S','s','f','F','f*','B','B*','b','b*','INLINE IMAGE'):candidates.append(i)
    instrumented=[];positions={idx:cid for cid,idx in enumerate(candidates)}
    for idx,inst in enumerate(drawing):
        if idx in positions:instrumented.append(([q.Name.Span,q.Dictionary(MCID=positions[idx])],q.Operator('BDC')))
        instrumented.append(inst)
        if idx in positions:instrumented.append(([],q.Operator('EMC')))
    old=original.obj.get('/Contents')
    try:
        original.obj.Contents=session.pdf.make_stream(q.unparse_content_stream(instrumented))
        data=session.snapshot()
    finally:original.obj.Contents=old
    miner=engine.PDFDocument(engine.PDFParser(BytesIO(data)))
    mp=next(p for i,p in enumerate(engine.PDFPage.create_pages(miner)) if i==page)
    target=records(engine,mp);source=session.source_records(page)
    available=[((cid,j),r) for (stream,cid),rs in target.items() if stream==0 for j,r in enumerate(rs)]
    claimed={};by_source={};source_text={}
    for tag in session.reference.tags:
        for ref in tag.refs:
            if ref.page!=page or ref.mcid is None:continue
            key=session.ref_key(ref)
            if key in by_source:raise ValueError('Duplicate source content ownership')
            expected=source.get((ref.stream,ref.mcid),[])
            if not expected:raise ValueError(f'{tag.path}: source content cannot be located')
            matched=locate_records(expected,available)
            for primitive in matched:
                if primitive in claimed:raise ValueError('Two source tags claim the same original content')
                claimed[primitive]=key
            by_source[key]=matched;source_text[key]=''.join(r[1] for r in expected)
    assignments={}
    for cid,idx in enumerate(candidates):
        rs=target.get((0,cid),[]);owners={claimed.get((cid,j)) for j in range(len(rs))}
        if owners=={None} or not owners:continue
        if len(owners)!=1 or None in owners:raise ValueError('Original artwork contains multiple tags or mixed tagged/untagged content that cannot be split safely')
        assignments[idx]=next(iter(owners))
    for key,matched in by_source.items():
        if any(candidates[cid] not in assignments for cid,j in matched):raise ValueError('Some source content could not be linked')
        text=''.join(r[1] for cid,idx in enumerate(candidates) if assignments.get(idx)==key for r in target.get((0,cid),[]))
        if text!=source_text[key]:raise ValueError('Matched text order differs; manual review is required')
    output=[];mapping=defaultdict(list);active=None;next_id=0
    # Merge consecutive paint candidates for the same source reference into one MCID.
    for idx,inst in enumerate(drawing):
        if idx in positions:
            key=assignments.get(idx)
            marker=key if key is not None else ('artifact',) if idx in artifacts else None
            if marker!=active:
                if active is not None:output.append(([],q.Operator('EMC')))
                if key is not None:
                    mapping[key].append(next_id)
                    output.append(([q.Name.Span,q.Dictionary(MCID=next_id)],q.Operator('BDC')));next_id+=1
                elif marker is not None:output.append(([q.Name.Artifact],q.Operator('BMC')))
                active=marker
        output.append(inst)
    if active is not None:output.append(([],q.Operator('EMC')))
    return q.unparse_content_stream(output),dict(mapping)
