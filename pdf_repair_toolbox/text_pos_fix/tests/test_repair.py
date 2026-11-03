import sys
from pathlib import Path
from io import BytesIO
import pytest
import pikepdf as q
import pymupdf as fitz
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repair_core import Document


def make_pdf(path, content=None, rotation=0):
    pdf = q.Pdf.new()
    page = pdf.add_blank_page(page_size=(240, 160))
    page.obj.Resources = q.Dictionary(Font=q.Dictionary(F1=pdf.make_indirect(q.Dictionary(Type=q.Name.Font, Subtype=q.Name.Type1, BaseFont=q.Name.Helvetica))))
    page.obj.Rotate = rotation
    page.obj.Contents = pdf.make_stream(content or b'BT /F1 24 Tf 30 80 Td (Hello) Tj ET 1 1 1 rg 0 0 240 160 re f')
    pdf.save(path)


def ink(doc):
    w, h, data = doc.render(0)
    return sum(v < 180 for v in data)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_reveal_geometry_undo_save_idempotence(tmp_path, rotation):
    source = tmp_path / 'source.pdf'
    make_pdf(source, rotation=rotation)
    original = source.read_bytes()
    doc = Document(source)
    old_items = doc.text_items(0)
    assert ink(doc) == 0
    assert doc.repair()[0].state == 'Ready'
    assert ink(doc) > 100
    assert doc.text_items(0) == old_items
    snapshot = doc.snapshot()
    assert doc.repair()[0].state == 'Already repaired'
    assert doc.snapshot() == snapshot
    target = tmp_path / 'out.pdf'
    doc.save(target)
    assert source.read_bytes() == original
    with pytest.raises(ValueError):
        doc.save(source)
    doc.undo()
    assert ink(doc) == 0
    doc.close()
    repaired = Document(target)
    assert ink(repaired) > 100
    repaired.close()


def test_nested_form_text_is_reported(tmp_path):
    source = tmp_path / 'nested.pdf'
    make_pdf(source)
    with q.open(source) as pdf:
        form = pdf.make_stream(b'BT /F1 12 Tf (Nested) Tj ET 0 0 10 10 re f')
        form.Type = q.Name.XObject
        form.Subtype = q.Name.Form
        form.BBox = q.Array([0, 0, 240, 160])
        form.Resources = pdf.pages[0].Resources
        pdf.pages[0].Resources.XObject = q.Dictionary(X=form)
        pdf.pages[0].Contents = pdf.make_stream(b'/X Do')
        pdf.save(tmp_path / 'form.pdf')
    doc = Document(tmp_path / 'form.pdf')
    assert doc.plans[0].state == 'Skipped'
    assert 'Form' in doc.plans[0].reason
    before = doc.snapshot()
    doc.repair()
    assert doc.snapshot() == before
    doc.close()


@pytest.mark.parametrize('content,reason', [
    (b'BT /F1 20 Tf 4 Tr (Mask) Tj ET', 'clipping'),
    (b'/P <</MCID 0>> BDC BT /F1 20 Tf (Text) Tj ET 0 0 30 30 re f EMC', 'both text and artwork'),
    (b'Q', 'Unbalanced'),
])
def test_unsupported_is_unchanged(tmp_path, content, reason):
    source = tmp_path / 'source.pdf'
    make_pdf(source, content)
    doc = Document(source)
    assert doc.plans[0].state == 'Skipped'
    assert reason in doc.plans[0].reason
    before = doc.snapshot()
    doc.repair()
    assert doc.snapshot() == before
    doc.close()


def test_mcid_unique_and_invisible_text(tmp_path):
    source = tmp_path / 'tag.pdf'
    make_pdf(source, b'/P <</MCID 0>> BDC BT /F1 20 Tf 20 80 Td (Visible) Tj ET EMC /Span <</MCID 1>> BDC BT /F1 12 Tf 3 Tr 20 40 Td (Hidden) Tj ET EMC 1 1 1 rg 0 0 240 160 re f')
    doc = Document(source)
    doc.repair()
    instructions = list(q.parse_content_stream(doc.pdf.pages[0]))
    ids = [int(i.operands[1].MCID) for i in instructions if str(i.operator) == 'BDC']
    assert ids == [0, 1]
    assert {x['type'] for x in doc.text_items(0)} == {0, 3}
    assert ink(doc) > 0
    doc.close()


def test_transform_clip_multiple_streams(tmp_path):
    source = tmp_path / 'source.pdf'
    make_pdf(source)
    with q.open(source) as pdf:
        page = pdf.pages[0]
        page.Contents = q.Array([pdf.make_stream(b'q 1 0.2 0 1 10 5 cm 0 0 240 160 re W n BT /F1 20 Tf 10 50 Td (Clipped) Tj ET Q'), pdf.make_stream(b'1 1 1 rg 0 0 240 160 re f')])
        pdf.save(tmp_path / 'multi.pdf')
    doc = Document(tmp_path / 'multi.pdf')
    assert ink(doc) == 0
    doc.repair()
    assert ink(doc) > 0
    doc.close()


def test_text_only_nested_form(tmp_path):
    source = tmp_path / 'source.pdf'
    make_pdf(source)
    with q.open(source) as pdf:
        page = pdf.pages[0]
        form = pdf.make_stream(b'BT /F1 20 Tf 20 80 Td (Nested) Tj ET')
        form.Type = q.Name.XObject; form.Subtype = q.Name.Form
        form.BBox = q.Array([0, 0, 240, 160])
        form.Resources = q.Dictionary(Font=page.Resources.Font)
        page.Resources.XObject = q.Dictionary(X=form)
        page.Contents = pdf.make_stream(b'q 1 0 0 1 10 10 cm /X Do Q 1 1 1 rg 0 0 240 160 re f')
        pdf.save(tmp_path / 'form.pdf')
    doc = Document(tmp_path / 'form.pdf')
    assert ink(doc) == 0
    assert doc.repair()[0].state == 'Ready'
    assert ink(doc) > 100
    doc.close()


def test_image_occlusion_and_encryption(tmp_path):
    from PIL import Image
    source = tmp_path / 'source.pdf'
    make_pdf(source)
    image_data = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(image_data, format='PNG')
    with fitz.open(source) as pdf:
        pdf[0].insert_image(pdf[0].rect, stream=image_data.getvalue(), overlay=True)
        pdf.save(tmp_path / 'image.pdf')
    with q.open(tmp_path / 'image.pdf') as pdf:
        pdf.save(tmp_path / 'encrypted.pdf', encryption=q.Encryption(owner='owner', user='user', R=6))
    doc = Document(tmp_path / 'encrypted.pdf', 'user')
    assert ink(doc) == 0
    doc.repair()
    assert ink(doc) > 100
    target = tmp_path / 'saved.pdf'
    doc.save(target)
    with q.open(target, password='user') as pdf:
        assert pdf.is_encrypted
    doc.close()


def test_real_tag_tree_survives(tmp_path):
    source = tmp_path / 'source.pdf'
    make_pdf(source, b'/P <</MCID 0>> BDC BT /F1 20 Tf 20 80 Td (Tagged) Tj ET EMC 1 1 1 rg 0 0 240 160 re f')
    with q.open(source) as pdf:
        root = pdf.make_indirect(q.Dictionary(Type=q.Name.StructTreeRoot))
        tag = pdf.make_indirect(q.Dictionary(Type=q.Name.StructElem, S=q.Name.P, P=root, Pg=pdf.pages[0].obj, K=0))
        root.K = q.Array([tag])
        tree = q.NumberTree.new(pdf); tree[0] = q.Array([tag]); root.ParentTree = tree.obj
        pdf.pages[0].obj.StructParents = 0
        pdf.Root.StructTreeRoot = root; pdf.Root.MarkInfo = q.Dictionary(Marked=True)
        pdf.save(tmp_path / 'tagged.pdf')
    doc = Document(tmp_path / 'tagged.pdf')
    doc.repair(); doc.save(tmp_path / 'out.pdf'); doc.close()
    with q.open(tmp_path / 'out.pdf') as pdf:
        root = pdf.Root.StructTreeRoot
        assert root.K[0].K == 0
        assert root.K[0].Pg == pdf.pages[0].obj
        assert q.NumberTree(root.ParentTree)[0][0] == root.K[0]


def test_batch_rollback_on_failed_verification(tmp_path, monkeypatch):
    source = tmp_path / 'source.pdf'; make_pdf(source)
    doc = Document(source); before = doc.snapshot()
    def fail(*args): raise ValueError('verification failed')
    monkeypatch.setattr(doc, '_verify_geometry', fail)
    with pytest.raises(ValueError, match='verification failed'): doc.repair()
    assert doc.snapshot() == before
    assert not doc.history and not doc.dirty
    doc.close()
