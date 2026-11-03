import sys
from pathlib import Path
from hashlib import sha256
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pikepdf as q
import pymupdf as fitz
import pytest
from inserter_core import Editor,kids

@pytest.fixture
def sample(tmp_path):
    pdf=q.new(); page=pdf.add_blank_page(page_size=(400,400))
    font=pdf.make_indirect(q.Dictionary(Type=q.Name.Font,Subtype=q.Name.Type1,BaseFont=q.Name.Helvetica))
    page.obj.Resources=q.Dictionary(Font=q.Dictionary(F1=font))
    page.obj.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC BT /F1 20 Tf 30 340 Td (Existing content) Tj ET EMC\nBT /F1 18 Tf 30 280 Td (Untagged text) Tj ET\n0 0 1 rg 30 100 160 80 re f')
    root=pdf.make_indirect(q.Dictionary(Type=q.Name.StructTreeRoot))
    doc=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.Document,P=root))
    tag=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P,P=doc,Pg=page.obj,K=0))
    doc.K=tag; root.K=doc; page.obj.StructParents=0
    root.ParentTree=pdf.make_indirect(q.Dictionary(Nums=q.Array([0,q.Array([tag])]))); root.ParentTreeNextKey=1
    pdf.Root.StructTreeRoot=root; pdf.Root.MarkInfo=q.Dictionary(Marked=True)
    path=tmp_path/'sample.pdf'; pdf.save(path); pdf.close(); return path

def get_document(ed): return ed.nodes['root.0'].obj

@pytest.mark.parametrize('position,index,expected',[
 ('Before selected',1,['TD','TD','P']),('After selected',1,['P','TD','TD']),
 ('First children',1,['TD','TD','P']),('Last children',1,['P','TD','TD']),
 ('At child position',1,['TD','TD','P']),('At child position',2,['P','TD','TD'])])
def test_consecutive_placement(sample,position,index,expected):
    ed=Editor(sample)
    anchor='root.0.0' if 'selected' in position else 'root.0'
    keys=ed.insert(anchor,position,2,'TD',child_index=index)
    children=kids(get_document(ed))
    assert [str(x.S).lstrip('/') for x in children]==expected
    assert len(keys)==2
    for tag in children:
        assert tag.P.objgen==get_document(ed).objgen
    ed.undo(); assert len(kids(get_document(ed)))==1
    ed.close()

def test_text_properties_and_save(sample,tmp_path):
    digest=sha256(sample.read_bytes()).digest(); ed=Editor(sample)
    ed.insert('root.0','Last children',3,'P',{'title':'Paragraph {n}','actual':'Hello {n}'})
    path=tmp_path/'saved.pdf'; ed.save(path)
    with q.open(path) as pdf:
        tags=list(pdf.Root.StructTreeRoot.K.K)
        assert [str(t.T) for t in tags[1:]]==['Paragraph 1','Paragraph 2','Paragraph 3']
        assert str(tags[3].ActualText)=='Hello 3'
    assert sha256(sample.read_bytes()).digest()==digest
    with pytest.raises(ValueError): ed.save(sample)
    ed.close()

def test_scan_attach_untagged_and_move_existing(sample,tmp_path):
    ed=Editor(sample); sources=ed.scan_content(0)
    assert len(sources)==3
    assert 'Existing content' in sources[0].text
    assert 'Untagged text' in sources[1].text
    assert all(c.bounds for c in sources)
    chosen=[sources[1],sources[0],sources[2]]
    ed.insert('root.0','Last children',3,'Span',sources=chosen,scan_version=ed.version)
    tags=kids(get_document(ed)); assert len(tags)==4
    assert kids(tags[0])==[]
    assert [int(t.K.MCID) for t in tags[1:]]==[1,0,2]
    owners=q.NumberTree(ed.root.ParentTree)[0]
    assert owners[0].objgen==tags[2].objgen
    assert owners[1].objgen==tags[1].objgen
    assert owners[2].objgen==tags[3].objgen
    out=tmp_path/'attached.pdf'; ed.save(out)
    with fitz.open(sample) as original,fitz.open(out) as edited:
        assert original[0].get_pixmap().samples==edited[0].get_pixmap().samples
    reopened=Editor(out)
    rescanned=reopened.scan_content(0)
    assert len(rescanned)==3
    assert {c.text for c in rescanned if c.text}=={'Existing content','Untagged text'}
    reopened.close(); ed.close()

def test_insert_between_content_references(sample):
    ed=Editor(sample)
    source=ed.scan_content(0)[0]
    ed.insert('root.0.0.0','After selected',1,'P',sources=[source],scan_version=ed.version)
    # Moving scalar /K into a newly inserted child preserves the chosen boundary.
    p=kids(get_document(ed))[0]
    assert len(kids(p))==1 and str(kids(p)[0].S)=='/P'
    assert int(kids(p)[0].K.MCID)==0
    ed.close()

def test_untagged_pdf_and_rollback(tmp_path):
    path=tmp_path/'untagged.pdf'
    with q.new() as pdf:
        pdf.add_blank_page(); pdf.save(path)
    ed=Editor(path)
    ed.insert('root','Last children',2,'Document')
    assert len(kids(ed.root))==2
    ed.undo(); assert ed.root is None
    with pytest.raises(ValueError): ed.insert('root','Last children',0,'P')
    assert ed.root is None
    ed.close()

def test_large_count_and_stale_content(sample):
    ed=Editor(sample); source=ed.scan_content(0)[0]; version=ed.version
    ed.insert('root.0','Last children',1001,'TD')
    assert len(kids(get_document(ed)))==1002
    with pytest.raises(ValueError): ed.insert('root.0','Last children',1,'P',sources=[source],scan_version=version)
    ed.close()

def test_form_reference_moves_and_parent_tree_is_updated(tmp_path):
    sample=Path(__file__).resolve().parents[1]/'demo_tagged.pdf'
    ed=Editor(sample)
    form=next(c for c in ed.scan_content(0) if c.stream)
    assert form.text=='Form content' and form.bounds
    ed.insert('root.0','Last children',1,'Span',sources=[form],scan_version=ed.version)
    tag=kids(get_document(ed))[-1]
    assert tag.K.Stm.objgen==form.ref.Stm.objgen
    assert q.NumberTree(ed.root.ParentTree)[int(form.ref.Stm.StructParents)][0].objgen==tag.objgen
    target=tmp_path/'form.pdf'; ed.save(target)
    other=Editor(target)
    source=next(c for c in other.scan_content(0) if c.stream)
    assert source.text=='Form content' and source.bounds
    other.close(); ed.close()

def test_inconsistent_ownership_rolls_back(sample):
    ed=Editor(sample); source=ed.scan_content(0)[0]
    wrong=ed.pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P,P=ed.root))
    q.NumberTree(ed.root.ParentTree)[0]=q.Array([wrong])
    count=len(ed.order)
    with pytest.raises(ValueError,match='inconsistent'):
        ed.insert('root.0','Last children',1,'P',sources=[source],scan_version=ed.version)
    assert len(ed.order)==count
    assert not ed.undo_data
    assert not ed.dirty
    ed.close()

def test_encrypted_insert_and_save(sample,tmp_path):
    locked=tmp_path/'locked.pdf'
    with q.open(sample) as pdf:
        pdf.save(locked,encryption=q.Encryption(owner='owner',user='password'))
    ed=Editor(locked,'password')
    sources=ed.scan_content(0)
    ed.insert('root.0','Last children',1,'P',sources=[sources[1]],scan_version=ed.version)
    dest=tmp_path/'encrypted_copy.pdf'; ed.save(dest)
    with q.open(dest,password='password') as pdf:
        assert pdf.is_encrypted
        assert len(pdf.Root.StructTreeRoot.K.K)==2
    ed.close()
