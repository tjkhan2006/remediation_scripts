import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inserter_core import Editor,kids
from tree_filter import filter_tree

DEMO=Path(__file__).resolve().parents[1]/'demo_tagged.pdf'

def test_type_filter_keeps_ancestors_contents_and_original_anchors():
    ed=Editor(DEMO)
    matches,visible=filter_tree(ed,role='TH')
    assert len(matches)==2
    assert all(str(ed.nodes[k].obj.S)=='/TH' for k in matches)
    for key in matches:
        assert any(ed.parents[k]==key and not ed.nodes[k].structure for k in visible if k!='root')
        parent=ed.parents[key]
        while parent!='root':
            assert parent in visible
            parent=ed.parents[parent]
    assert not any(ed.nodes[k].structure and str(ed.nodes[k].obj.S)=='/TD' for k in visible if k!='root')
    # A filtered anchor still inserts into the actual PDF array at its original slot.
    selected=sorted(matches)[-1]
    original=ed.nodes[selected]
    parent=original.parent; slot=original.slot
    ed.insert(selected,'After selected',2,'Span')
    assert [str(x.S) for x in kids(parent)[slot+1:slot+3]]==['/Span','/Span']
    ed.close()

def test_all_tags_empty_results_and_metadata_search():
    ed=Editor(DEMO)
    matches,visible=filter_tree(ed)
    assert matches==set(ed.order)
    assert visible==set(ed.order)|{'root'}
    matches,visible=filter_tree(ed,role='Nonexistent')
    assert not matches and visible=={'root'}
    matches,_=filter_tree(ed,query='BLUE RECTANGLE',role='CustomFigure')
    assert len(matches)==1
    matches,_=filter_tree(ed,query='BLUE RECTANGLE',role='TH')
    assert not matches
    ed.close()
