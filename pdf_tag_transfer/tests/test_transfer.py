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
    s=Transfer(original,source)
    assert len(s.relationship_issues)==1
    assert s.relationship_issues[0]['path'].endswith('/Ref[0]')
    assert '/Ref' not in s.nodes[1]
    s.step();s.undo();s.step()
    assert len(s.relationship_issues)==1
    out=tmp_path/'partial.pdf'
    with pytest.raises(ValueError,match='partial-save confirmation'):s.save(out)
    assert not out.exists()
    s.save(out,allow_unresolved_relationships=True)
    with q.open(out) as pdf: assert '/Ref' not in pdf.Root.StructTreeRoot.K[0].K[0]
    s.close()


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


def test_mixed_refs_keep_valid_targets_and_report_missing_ones(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        first,second=pdf.Root.StructTreeRoot.K.K
        missing=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P))
        first.Ref=q.Array([missing,second,missing]);pdf.save(source)
    before=source.read_bytes();s=Transfer(original,source)
    assert len(s.relationship_issues)==2
    assert len(s.nodes[1].Ref)==1 and s.nodes[1].Ref[0].objgen==s.nodes[2].objgen
    assert s.relationship_issues[0]['source_object']==s.relationship_issues[1]['source_object']
    from types import SimpleNamespace
    from pdf_tag_transfer import App
    fake=SimpleNamespace(session=s)
    assert App.tag_state(fake,s.reference.tags[1])=='Needs review'
    assert App.tag_state(fake,s.reference.tags[0])=='Needs review'
    s.step(); assert not s.unresolved()  # Relationship issues are independent of content success.
    assert App.tag_state(fake,s.reference.tags[1])=='Needs review'
    out=tmp_path/'partial_mixed.pdf';s.save(out,allow_unresolved_relationships=True);s.close()
    with q.open(out) as pdf:
        first,second=pdf.Root.StructTreeRoot.K[0].K
        assert len(first.Ref)==1 and first.Ref[0].objgen==second.objgen
    assert source.read_bytes()==before


def test_gui_partial_relationship_save_requires_confirmation(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pdf_tag_transfer as gui
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        missing=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P))
        pdf.Root.StructTreeRoot.K.K[0].Ref=q.Array([missing]);pdf.save(source)
    s=Transfer(original,source);s.step()
    out=tmp_path/'gui_partial.pdf';prompts=[]
    monkeypatch.setattr(gui.filedialog,'asksaveasfilename',lambda **kw:str(out))
    monkeypatch.setattr(gui.messagebox,'askyesno',lambda title,text:prompts.append(text) or False)
    fake=SimpleNamespace(session=s,busy=False,running=False,job=lambda fn,done:fn())
    gui.App.save(fake)
    assert len(prompts)==1 and 'omitted' in prompts[0] and not out.exists()
    monkeypatch.setattr(gui.messagebox,'askyesno',lambda *args:True)
    gui.App.save(fake);assert out.exists();s.close()


def assert_population(s,out):
    assert s.states==['Transferred'],s.messages
    assert not s.unresolved()
    s.save(out)
    d=Document(out)
    assert d.selection(1,0)[1]=='First'
    assert d.selection(2,0)[1]=='Second'
    assert all(d.selection(i,0)[0] for i in (1,2))
    d.close()


def test_regrouped_text_operators_populate_tags_not_just_tree(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        data=pdf.pages[0].obj.Contents.read_bytes().replace(b'(First) Tj',b'[(Fi) 0 (rst)] TJ')
        pdf.pages[0].obj.Contents=pdf.make_stream(data);pdf.save(source)
    s=Transfer(original,source);s.step()
    assert_population(s,tmp_path/'matched.pdf')
    assert 'position matching' in s.messages[0]
    s.undo();assert not s.links
    s.step();assert_population(s,tmp_path/'replayed.pdf');s.close()


def test_single_original_text_run_is_split_between_source_tags(tmp_path):
    original,source=pair(tmp_path)
    with q.open(original,allow_overwriting_input=True) as pdf:
        pdf.pages[0].obj.Contents=pdf.make_stream(b'BT /F1 20 Tf 30 340 Td (FirstSecond) Tj ET');pdf.save(original)
    with q.open(source,allow_overwriting_input=True) as pdf:
        data=pdf.pages[0].obj.Contents.read_bytes().replace(b'0 -30 Td ',b'')
        pdf.pages[0].obj.Contents=pdf.make_stream(data);pdf.save(source)
    before=original.read_bytes();s=Transfer(original,source);s.step()
    assert_population(s,tmp_path/'split.pdf');s.close()
    assert original.read_bytes()==before


def test_renamed_font_resource_matched_by_content(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        fonts=pdf.pages[0].obj.Resources.Font;fonts.SourceFont=fonts.F1;del fonts.F1
        data=pdf.pages[0].obj.Contents.read_bytes().replace(b'/F1 ',b'/SourceFont ')
        pdf.pages[0].obj.Contents=pdf.make_stream(data);pdf.save(source)
    s=Transfer(original,source);s.step();assert_population(s,tmp_path/'font.pdf');s.close()


def test_tree_only_output_is_blocked_and_counts_show_missing_content(tmp_path):
    original,source=pair(tmp_path,True);s=Transfer(original,source)
    s.step();summary=s.content_summary()
    assert summary['linked_content_references']==0
    assert summary['unresolved_content_references']==2
    with pytest.raises(ValueError,match='empty tag tree'):
        s.save(tmp_path/'empty.pdf',allow_unresolved_content=True)
    assert not (tmp_path/'empty.pdf').exists();s.close()


def test_save_verifies_actual_content_instead_of_trusting_mapping(tmp_path):
    original,source=pair(tmp_path);s=Transfer(original,source);s.step()
    # Simulate the reported symptom: a populated in-memory mapping but missing saved /K.
    s.nodes[1].K=q.Array([])
    with pytest.raises(ValueError,match='saved tag content references'):
        s.save(tmp_path/'bad.pdf')
    assert not (tmp_path/'bad.pdf').exists();s.close()


def test_image_and_vector_content_are_populated_with_text(tmp_path):
    original,source=pair(tmp_path)
    for path,tagged in ((original,False),(source,True)):
        with q.open(path,allow_overwriting_input=True) as pdf:
            image=pdf.make_stream(b'\xff\x00\x00\x00\xff\x00')
            image.Type=q.Name.XObject;image.Subtype=q.Name.Image;image.Width=2;image.Height=1
            image.ColorSpace=q.Name.DeviceRGB;image.BitsPerComponent=8
            name='/SourceImage' if tagged else '/BaseImage'
            pdf.pages[0].obj.Resources.XObject=q.Dictionary({name:image})
            vector=b'q 0 0 1 rg 30 40 60 20 re f Q'
            image_ops=b'q 60 0 0 30 150 80 cm '+name.encode()+b' Do Q'
            if tagged:
                doc=pdf.Root.StructTreeRoot.K
                for mcid in (2,3):
                    tag=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.Figure,P=doc,Pg=pdf.pages[0].obj,K=mcid))
                    doc.K.append(tag)
                vector=b'/Figure <</MCID 2>> BDC '+vector+b' EMC'
                image_ops=b'/Figure <</MCID 3>> BDC '+image_ops+b' EMC'
            pdf.pages[0].obj.Contents=pdf.make_stream(pdf.pages[0].obj.Contents.read_bytes()+b'\n'+vector+b'\n'+image_ops)
            pdf.save(path)
    s=Transfer(original,source);s.step()
    assert s.states==['Transferred'],s.messages
    out=tmp_path/'artwork.pdf';s.save(out);d=Document(out)
    assert d.selection(3,0)[0] and d.selection(4,0)[0]
    assert s.content_summary()['linked_content_references']==4
    d.close();s.close()


@pytest.mark.parametrize('explicit_page',[True,False])
def test_source_form_reference_can_link_to_original_form_placement(tmp_path,explicit_page):
    original,source=pair(tmp_path)
    for path,tagged in ((original,False),(source,True)):
        with q.open(path,allow_overwriting_input=True) as pdf:
            data=b'BT /F1 14 Tf 100 150 Td (Inside Form) Tj ET'
            if tagged:data=b'/P <</MCID 7>> BDC '+data+b' EMC'
            form=pdf.make_stream(data);form.Type=q.Name.XObject;form.Subtype=q.Name.Form
            form.BBox=q.Array([0,0,400,400]);form.Resources=q.Dictionary(Font=pdf.pages[0].obj.Resources.Font)
            if tagged:form.StructParents=8
            pdf.pages[0].obj.Resources.XObject=q.Dictionary(Fm=form)
            pdf.pages[0].obj.Contents=pdf.make_stream(pdf.pages[0].obj.Contents.read_bytes()+b'\n/Fm Do')
            if tagged:
                doc=pdf.Root.StructTreeRoot.K
                tag=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P,P=doc,K=q.Dictionary(Type=q.Name.MCR,Stm=form,Pg=pdf.pages[0].obj,MCID=7)))
                if not explicit_page:del tag.K.Pg
                doc.K.append(tag)
            pdf.save(path)
    s=Transfer(original,source);s.step()
    assert s.states==['Transferred'],s.messages
    out=tmp_path/'form.pdf';s.save(out);d=Document(out)
    assert d.selection(3,0)[1]=='Inside Form' and d.selection(3,0)[0]
    assert not s.unresolved();d.close();s.close()


def test_real_multibyte_font_content_survives_matching(tmp_path):
    original=tmp_path/'original.pdf';source=tmp_path/'source.pdf'
    with fitz.open() as doc:
        page=doc.new_page();page.insert_text((50,60),'测试',fontname='china-s',fontsize=18);doc.save(original)
    with q.open(original) as pdf:
        page=pdf.pages[0];fonts=page.obj.Resources.Font
        old=str(next(iter(fonts.keys())));fonts.RenamedFont=fonts[old];del fonts[old]
        ops=b'\n'.join(s.read_bytes() for s in page.obj.Contents) if isinstance(page.obj.Contents,q.Array) else page.obj.Contents.read_bytes()
        ops=ops.replace(old.encode(),b'/RenamedFont')
        page.obj.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC '+ops+b' EMC')
        root=pdf.make_indirect(q.Dictionary(Type=q.Name.StructTreeRoot));pdf.Root.StructTreeRoot=root
        doc=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.Document,P=root));root.K=doc
        tag=pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P,P=doc,Pg=page.obj,K=0));doc.K=tag
        pdf.save(source)
    s=Transfer(original,source);s.step()
    assert s.states==['Transferred'],s.messages
    out=tmp_path/'cid.pdf';s.save(out);d=Document(out)
    assert d.selection(1,0)[1]=='测试';d.close();s.close()


def test_parenttree_corruption_is_detected_before_saving(tmp_path):
    original,source=pair(tmp_path);s=Transfer(original,source);s.step()
    owners=q.NumberTree(s.root.ParentTree)[0];owners[0]=s.nodes[2]
    with pytest.raises(ValueError,match='ParentTree'):
        s.save(tmp_path/'wrong_owner.pdf')
    assert not (tmp_path/'wrong_owner.pdf').exists();s.close()


def test_content_free_stream_cannot_pass_as_populated_tags(tmp_path):
    original,source=pair(tmp_path);s=Transfer(original,source);s.step()
    # Retain artwork and tree/ParentTree but remove all actual marked-content wrappers.
    from transfer_core import stream_parts
    drawing,_=stream_parts(s.pdf.pages[0]);s.pdf.pages[0].obj.Contents=s.pdf.make_stream(q.unparse_content_stream(drawing))
    with pytest.raises(ValueError,match='saved tag text'):
        s.save(tmp_path/'unpopulated.pdf')
    assert not (tmp_path/'unpopulated.pdf').exists();s.close()


def test_partial_content_save_requires_opt_in(tmp_path):
    original,source=pair(tmp_path)
    with q.open(original,allow_overwriting_input=True) as pdf:
        pdf.add_blank_page(page_size=(400,400));pdf.save(original)
    with q.open(source,allow_overwriting_input=True) as pdf:
        page=pdf.add_blank_page(page_size=(400,400));page.obj.Resources=pdf.pages[0].obj.Resources
        page.obj.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC BT /F1 20 Tf 30 340 Td (Changed) Tj ET EMC')
        doc=pdf.Root.StructTreeRoot.K
        doc.K.append(pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem,S=q.Name.P,P=doc,Pg=page.obj,K=0)))
        pdf.save(source)
    s=Transfer(original,source);s.step();s.step()
    assert s.states==['Transferred','Needs review']
    with pytest.raises(ValueError,match='partial-save confirmation'):s.save(tmp_path/'partial_content.pdf')
    s.save(tmp_path/'partial_content.pdf',allow_unresolved_content=True)
    assert s.content_summary()['linked_content_references']==2
    assert s.content_summary()['unresolved_content_references']==1
    s.close()


def test_explicit_default_coordinate_values_do_not_block_content(tmp_path):
    original,source=pair(tmp_path)
    with q.open(source,allow_overwriting_input=True) as pdf:
        page=pdf.pages[0];page.obj.Rotate=0;page.obj.UserUnit=1
        page.obj.CropBox=q.Array([0,0,400,400]);page.obj.MediaBox=q.Array([0.0,0.0,400.0,400.0])
        pdf.save(source)
    s=Transfer(original,source);s.step();assert_population(s,tmp_path/'defaults.pdf');s.close()
