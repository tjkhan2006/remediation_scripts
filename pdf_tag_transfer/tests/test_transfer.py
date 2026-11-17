import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pikepdf as q
import pymupdf as fitz
import pytest
from transfer_core import Transfer, Document


def pair(tmp_path, changed=False):
    original=tmp_path/'original.pdf'; source=tmp_path/'source.pdf'
    pdf=q.new(); page=pdf.add_blank_page(page_size=(400,400))
    font=pdf.make_indirect(q.Dictionary(Type=q.Name.Font,Subtype=q.Name.Type1,BaseFont=q.Name.Helvetica))
    page.obj.Resources=q.Dictionary(Font=q.Dictionary(F1=font))
    drawing=b'BT /F1 20 Tf 30 340 Td (First) Tj 0 -30 Td (Second) Tj ET'
    page.obj.Contents=pdf.make_stream(drawing); pdf.save(original)
    root=pdf.make_indirect(q.Dictionary(Type=q.Name.StructTreeRoot))
    doc=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.Document,P=root))
    tags=[pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P,P=doc,Pg=page.obj,K=i,Alt=f'Alt {i}',ID=f'id{i}',A=q.Dictionary(O=q.Name.Table,RowSpan=1))) for i in range(2)]
    doc.K=q.Array(tags); root.K=doc; root.ParentTree=pdf.make_indirect(q.Dictionary(Nums=q.Array([0,q.Array(tags)])))
    pdf.Root.StructTreeRoot=root; page.obj.StructParents=0
    content=b'BT /F1 20 Tf 30 340 Td /P <</MCID 0>> BDC (First) Tj EMC 0 -30 Td /P <</MCID 1>> BDC (Second) Tj EMC ET'
    if changed:content=content.replace(b'First',b'Other')
    page.obj.Contents=pdf.make_stream(content); pdf.save(source);pdf.close()
    return original,source


def test_precise_text_boundaries_metadata_and_save(tmp_path):
    original,source=pair(tmp_path); before=original.read_bytes(); s=Transfer(original,source)
    assert s.step()==0 and s.states==['Transferred']
    assert len(s.links)==2 and not s.unresolved()
    out=tmp_path/'out.pdf'; s.save(out)
    d=Document(out)
    assert [t.role for t in d.tags]==['Document','P','P']
    assert d.tags[1].alt=='Alt 0'
    assert d.selection(1,0)[1]=='First'
    assert d.selection(2,0)[1]=='Second'
    with q.open(out) as pdf:
        assert len(q.NumberTree(pdf.Root.StructTreeRoot.ParentTree)[0])==2
        assert len(pdf.Root.StructTreeRoot.IDTree.Names)==4
    assert original.read_bytes()==before
    with pytest.raises(ValueError):s.save(original)
    s.undo(); assert not s.links and s.states==['Pending']
    s.step();assert len(s.links)==2
    d.close();s.close()


def test_changed_artwork_is_flagged_without_transfer(tmp_path):
    original,source=pair(tmp_path,True);s=Transfer(original,source)
    s.step();assert s.states==['Needs review'] and not s.links
    assert len(s.unresolved())==2
    s.close()


def test_duplicate_content_ownership_flagged(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        pdf.Root.StructTreeRoot.K.K[1].K=0;pdf.save(source)
    s=Transfer(original,source);s.step()
    assert s.states==['Needs review'];assert not s.links;s.close()


def test_tagged_base_rejected(tmp_path):
    original,source=pair(tmp_path)
    with pytest.raises(ValueError,match='original'):Transfer(source,source)


def test_hard_link_input_protected(tmp_path):
    original,source=pair(tmp_path);s=Transfer(original,source)
    alias=tmp_path/'alias.pdf';alias.hardlink_to(original)
    with pytest.raises(ValueError):s.save(alias)
    s.close()


def test_nested_mcid_rejected(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        content=pdf.pages[0].obj.Contents.read_bytes()
        pdf.pages[0].obj.Contents=pdf.make_stream(b'/Span <</MCID 8>> BDC '+content+b' EMC')
        pdf.save(source)
    s=Transfer(original,source);s.step()
    assert s.states==['Needs review'] and not s.links;s.close()


def test_forms_flagged(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        form=pdf.make_stream(b'');form.Type=q.Name.XObject;form.Subtype=q.Name.Form;form.BBox=q.Array([0,0,10,10]);form.StructParents=10
        pdf.pages[0].obj.Resources.XObject=q.Dictionary(Fm=form);pdf.save(source)
    s=Transfer(original,source);s.step()
    assert s.states==['Needs review'] and 'Form' in s.messages[0];s.close()


def test_duplicate_ids_rejected(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        pdf.Root.StructTreeRoot.K.K[1].ID='id0';pdf.save(source)
    with pytest.raises(ValueError,match='Duplicate source tag IDs'):Transfer(original,source)


def test_parenttree_fallback_for_missing_page(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        for tag in pdf.Root.StructTreeRoot.K.K: del tag.Pg
        pdf.save(source)
    s=Transfer(original,source);s.step();assert s.states==['Transferred']
    out=tmp_path/'fallback.pdf';s.save(out);d=Document(out)
    assert d.selection(1,0)[1]=='First' and d.selection(2,0)[1]=='Second'
    d.close();s.close()


def test_stream_attributes_and_classmap_survive_save_and_undo(tmp_path):
    import zlib
    original,source=pair(tmp_path)
    payload=b'Attribute stream payload with binary data: \x00\xff\n'
    encoded=zlib.compress(payload)
    with q.open(source,allow_overwriting_input=True) as pdf:
        attr=pdf.make_stream(encoded)
        attr.Filter=q.Name.FlateDecode
        attr.O=q.Name.Table
        attr.RowSpan=2
        attr.Custom=q.Dictionary(Label='preserved')
        root=pdf.Root.StructTreeRoot
        root.K.K[0].A=attr
        root.ClassMap=q.Dictionary(TestClass=q.Array([attr,1]))
        root.K.K[0].C=q.Name.TestClass
        pdf.save(source)
    original_bytes=original.read_bytes(); source_bytes=source.read_bytes()
    s=Transfer(original,source)
    assert isinstance(s.nodes[1].A,q.Stream)
    assert s.nodes[1].A.read_bytes()==payload
    assert s.nodes[1].A.read_raw_bytes()==encoded
    s.step();s.undo();s.step()
    out=tmp_path/'stream_attributes.pdf';s.save(out);s.close()
    with q.open(out) as pdf:
        attr=pdf.Root.StructTreeRoot.K[0].K[0].A
        assert isinstance(attr,q.Stream)
        assert attr.read_bytes()==payload and attr.RowSpan==2
        assert str(attr.Custom.Label)=='preserved'
        assert pdf.Root.StructTreeRoot.ClassMap.TestClass[0].read_bytes()==payload
    assert original.read_bytes()==original_bytes and source.read_bytes()==source_bytes


def test_stream_metadata_document_link_has_specific_error(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        attr=pdf.make_stream(b'test');attr.ForeignPage=pdf.pages[0].obj
        pdf.Root.StructTreeRoot.K.K[0].A=attr
        pdf.save(source)
    with pytest.raises(ValueError,match=r'/A/ForeignPage.*document structure'):
        Transfer(original,source)


def test_namespaces_crossmaps_and_refs_reconnect_after_undo_and_save(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        ns=pdf.make_indirect(q.Dictionary(Type=q.Name.Namespace,NS='urn:test:custom'))
        standard=pdf.make_indirect(q.Dictionary(Type=q.Name.Namespace,NS='http://iso.org/pdf2/ssn'))
        ns.RoleMapNS=q.Dictionary(CustomP=q.Array([q.Name.P,standard]))
        standard.RoleMapNS=q.Dictionary(Back=q.Array([q.Name.CustomP,ns]))
        schema=pdf.make_stream(b'<schema/>');ns.Schema=schema
        root=pdf.Root.StructTreeRoot;root.Namespaces=q.Array([ns,standard])
        first,second=root.K.K
        first.S=q.Name.CustomP;first.NS=ns;second.NS=ns
        first.Ref=q.Array([second]);second.Ref=q.Array([first])
        pdf.save(source,min_version='2.0')
    source_bytes=source.read_bytes()
    s=Transfer(original,source)
    assert s.nodes[1].Ref[0].objgen==s.nodes[2].objgen
    assert s.nodes[2].Ref[0].objgen==s.nodes[1].objgen
    assert s.nodes[1].NS.objgen==s.nodes[2].NS.objgen
    assert s.nodes[1].NS.RoleMapNS.CustomP[1].RoleMapNS.Back[1].objgen==s.nodes[1].NS.objgen
    s.step();s.undo();s.step()
    out=tmp_path/'namespaces.pdf';s.save(out);s.close()
    with q.open(out) as pdf:
        assert pdf.pdf_version=='2.0'
        root=pdf.Root.StructTreeRoot;first,second=root.K[0].K
        assert len(root.Namespaces)==2
        assert first.NS.objgen==root.Namespaces[0].objgen==second.NS.objgen
        assert first.Ref[0].objgen==second.objgen and second.Ref[0].objgen==first.objgen
        assert first.NS.Schema.read_bytes()==b'<schema/>'
        assert root.Namespaces[0].RoleMapNS.CustomP[1].objgen==root.Namespaces[1].objgen
    assert source.read_bytes()==source_bytes
    d=Document(out);assert d.selection(1,0)[1]=='First';d.close()


def test_tag_namespace_missing_from_root_list_is_registered(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        ns=pdf.make_indirect(q.Dictionary(Type=q.Name.Namespace,NS='urn:test:unlisted'))
        pdf.Root.StructTreeRoot.K.K[0].NS=ns;pdf.save(source,min_version='2.0')
    s=Transfer(original,source)
    assert len(s.root.Namespaces)==1 and s.nodes[1].NS.objgen==s.root.Namespaces[0].objgen
    s.close()


def test_unreachable_ref_is_diagnosed_by_tag_path(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        unreachable=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P))
        pdf.Root.StructTreeRoot.K.K[0].Ref=q.Array([unreachable]);pdf.save(source)
    with pytest.raises(ValueError,match=r'/Ref\[0\].*outside the recovered tag tree'):
        Transfer(original,source)


def test_ref_without_namespaces_preserves_forward_target_and_version(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        first,second=pdf.Root.StructTreeRoot.K.K
        first.Ref=q.Array([second]);second.Ref=q.Array([])
        pdf.save(source,min_version='1.5')
    s=Transfer(original,source);s.step();out=tmp_path/'refs.pdf';s.save(out);s.close()
    with q.open(out) as pdf:
        first,second=pdf.Root.StructTreeRoot.K[0].K
        assert first.Ref[0].objgen==second.objgen
        assert len(second.Ref)==0
        assert tuple(map(int,pdf.pdf_version.split('.'))) >= (1,5)
        assert '/Namespaces' not in pdf.Root.StructTreeRoot
