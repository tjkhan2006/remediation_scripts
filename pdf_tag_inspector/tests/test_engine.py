import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pikepdf
import pytest
from engine import Document, display_rect
from make_demo import make_demo


@pytest.fixture
def demo(tmp_path):
    path = tmp_path/'demo.pdf'
    make_demo(path)
    return path


def test_structure_filter_properties(demo):
    doc = Document(demo)
    assert doc.page_count == 2
    assert doc.tags[0].pages == {0, 1}
    assert len(doc.filter(role='TH')) == 2
    assert len(doc.filter(role='Figure')) == 2
    assert len(doc.filter(missing_alt=True)) == 1
    fig = doc.tags[doc.filter(query='figure-1')[0]]
    assert fig.identifier == 'figure-1'
    assert fig.expansion == 'Example figure'
    assert 'Artwork' in fig.classes
    assert '/ID' in fig.dictionary
    assert fig.inherited_language == 'en-US'
    assert doc.filter(query='blue rectangle') == [fig.id]
    assert fig.id not in doc.filter(page=1)
    doc.close()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('crop', [False, True])
def test_highlights_match_rendered_color(tmp_path, rotation, crop):
    path = tmp_path/'rotated.pdf'
    make_demo(path, rotation, crop)
    doc = Document(path)
    fig = doc.filter(query='figure-1')[0]
    boxes, _, note, colors = doc.selection(fig, 0)
    assert len(boxes) == 1
    w, h, pixels, _ = doc.render(0, 1)
    x0,y0,x1,y1 = boxes[0]
    # Sample a point just inside the blue illustration, away from its text.
    x,y = int(x0+(x1-x0)*.1), int(y0+(y1-y0)*.1)
    rgb = pixels[(y*w+x)*3:(y*w+x)*3+3]
    assert len(rgb) == 3 and rgb[2] > rgb[0]+80, (rotation,crop,boxes,rgb)
    assert 'DeviceRGB' in colors
    doc.close()


def test_mcid_scoping_named_properties_and_multipage(demo):
    doc = Document(demo)
    h = doc.filter(role='H1')[0]
    _, text, _, _ = doc.selection(h, 0)
    assert 'PDF accessibility explorer' in text
    assert 'Form content' not in text  # Both use MCID 0, but in different streams.
    span = doc.filter(role='Span')[0]
    boxes, text, _, _ = doc.selection(span, 0)
    assert text == 'Form content' and boxes[0][0] >= 340
    p = next(t for t in doc.tags if t.role == 'P' and t.pages == {0})
    assert 'Select a tag' in doc.selection(p.id, 0)[1]
    multi = next(t for t in doc.tags if t.role == 'P' and t.pages == {0,1})
    assert 'continues' in doc.selection(multi.id, 0)[1]
    assert 'continued' in doc.selection(multi.id, 1)[1]
    assert len(doc.selection(doc.filter(role='Link')[0], 1)[0]) == 2
    doc.close()


def test_edit_save_reopen_undo_original_unchanged(demo, tmp_path):
    original = hashlib.sha256(demo.read_bytes()).digest()
    doc = Document(demo)
    fig_id = doc.filter(query='figure-1')[0]
    values = dict(role='Figure', alt='New alt text', actual_text='Replacement', title='New title', language='fr-FR', expansion='Expanded')
    assert doc.edit(fig_id, values)
    target = tmp_path/'edited.pdf'
    doc.save_copy(target)
    assert hashlib.sha256(demo.read_bytes()).digest() == original
    reopened = Document(target)
    for field, value in values.items():
        assert getattr(reopened.tags[fig_id], field) == value
    assert reopened.tags[fig_id].identifier == 'figure-1'
    assert len(reopened.selection(fig_id, 0)[0]) == 1
    reopened.close()
    assert doc.undo() == fig_id
    assert doc.tags[fig_id].role == 'CustomFigure'
    assert doc.tags[fig_id].alt.startswith('Blue')
    with pytest.raises(ValueError):
        doc.save_copy(demo)
    doc.close()


def test_untagged_encrypted_and_export(tmp_path, demo):
    plain = tmp_path/'plain.pdf'
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(plain)
    doc = Document(plain)
    assert doc.tags == [] and doc.warnings
    assert doc.render(0, .2)[0] > 0
    doc.close()
    encrypted = tmp_path/'locked.pdf'
    with pikepdf.open(demo) as pdf:
        pdf.save(encrypted, encryption=pikepdf.Encryption(owner='owner', user='secret'))
    with pytest.raises(pikepdf.PasswordError):
        Document(encrypted)
    doc = Document(encrypted, 'secret')
    doc.save_copy(tmp_path/'encrypted_copy.pdf')
    with pikepdf.open(tmp_path/'encrypted_copy.pdf', password='secret') as pdf:
        assert pdf.is_encrypted
    report = tmp_path/'tags.json'
    ids = doc.filter(role='TH')
    doc.export(report, ids)
    assert len(json.loads(report.read_text())) == 2
    doc.close()


def test_parent_tree_page_fallback(demo, tmp_path):
    modified = tmp_path/'no_pg.pdf'
    with pikepdf.open(demo) as pdf:
        h = pdf.Root.StructTreeRoot.K.K[0]
        del h.Pg
        pdf.save(modified)
    doc = Document(modified)
    tag = doc.tags[doc.filter(role='H1')[0]]
    assert tag.pages == {0}
    assert 'PDF accessibility' in doc.selection(tag.id, 0)[1]
    doc.close()


def test_form_page_fallback(demo, tmp_path):
    modified = tmp_path/'form_no_pg.pdf'
    with pikepdf.open(demo) as pdf:
        tag = pdf.Root.StructTreeRoot.K.K[4]
        del tag.Pg
        del tag.K.Pg
        pdf.save(modified)
    doc = Document(modified)
    tag_id = doc.filter(role='Span')[0]
    assert doc.tags[tag_id].pages == {0}
    assert doc.selection(tag_id, 0)[1] == 'Form content'
    doc.close()


def test_invalid_edit_is_rejected_without_mutation(demo):
    doc = Document(demo)
    before = doc.tags[1].role
    with pytest.raises(ValueError):
        doc.edit(1, dict(role='bad tag', title='', alt='', actual_text='', language=''))
    assert doc.tags[1].role == before
    assert not doc.dirty
    doc.close()


def test_empty_fields_remove_properties_and_csv_is_safe(demo, tmp_path):
    doc = Document(demo)
    fig = doc.filter(query='figure-1')[0]
    doc.edit(fig, dict(role='Figure', title='=1+1', alt='', actual_text='', language='', expansion=''))
    assert '/Alt' not in doc._objects[fig]
    assert '/E' not in doc._objects[fig]
    report = tmp_path/'report.csv'
    doc.export(report,[fig])
    assert "'=1+1" in report.read_text(encoding='utf-8-sig')
    assert doc.filter(missing_alt=True) == [fig, len(doc.tags)-1]
    doc.close()
