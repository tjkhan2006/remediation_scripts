"""Generate a small tagged PDF for demonstration and regression tests."""
from pathlib import Path
import pikepdf
from pikepdf import Dictionary as D, Array as A, Name as N, String as S


def make_demo(path, rotation=0, crop=False):
    pdf = pikepdf.new()
    p1 = pdf.add_blank_page(page_size=(612, 792))
    p2 = pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(D(Type=N.Font, Subtype=N.Type1, BaseFont=N.Helvetica))
    for page in (p1, p2):
        page.obj.Resources = D(Font=D(F1=font))
    p1.obj.Rotate = rotation
    if crop:
        p1.obj.CropBox = A([30, 40, 580, 760])
    p1.obj.Contents = pdf.make_stream(b'''/H1 <</MCID 0>> BDC
BT /F1 26 Tf 54 720 Td (PDF accessibility explorer) Tj ET EMC
/P /Prop1 BDC
BT /F1 12 Tf 54 680 Td (Select a tag to inspect its content and properties.) Tj ET EMC
/Figure <</MCID 2>> BDC
0.15 0.45 0.75 rg 54 420 240 200 re f
1 1 1 rg BT /F1 18 Tf 74 510 Td (A tagged illustration) Tj ET EMC
/P <</MCID 3>> BDC
0 g BT /F1 12 Tf 54 380 Td (This paragraph continues on the next page.) Tj ET EMC
q 1 0 0 1 340 490 cm /Fm1 Do Q
BT /F1 10 Tf 54 60 Td (Demo document - page 1) Tj ET
''')
    p1.obj.Resources.Properties = D(Prop1=D(MCID=1))
    form = pdf.make_stream(b'/Span <</MCID 0>> BDC 0.7 0.1 0.1 rg BT /F1 13 Tf 0 0 Td (Form content) Tj ET EMC')
    form.Type, form.Subtype, form.BBox = N.XObject, N.Form, A([0, -10, 180, 30])
    form.Resources = D(Font=D(F1=font))
    p1.obj.Resources.XObject = D(Fm1=form)
    p2.obj.Contents = pdf.make_stream(b'''/P <</MCID 0>> BDC BT /F1 12 Tf 54 720 Td (Here is the continued paragraph on page two.) Tj ET EMC
/TH <</MCID 1>> BDC BT /F1 14 Tf 54 650 Td (Name) Tj ET EMC
/TH <</MCID 2>> BDC BT /F1 14 Tf 260 650 Td (Value) Tj ET EMC
/TD <</MCID 3>> BDC BT /F1 12 Tf 54 620 Td (Accessibility tags) Tj ET EMC
/TD <</MCID 4>> BDC BT /F1 12 Tf 260 620 Td (Inspectable) Tj ET EMC
/Link <</MCID 5>> BDC 0 0.25 0.7 rg BT /F1 12 Tf 54 540 Td (Example link) Tj ET EMC
''')
    root = pdf.make_indirect(D(Type=N.StructTreeRoot))
    pdf.Root.StructTreeRoot = root
    pdf.Root.MarkInfo = D(Marked=True)
    pdf.Root.Lang = S('en-US')
    root.RoleMap = D(CustomFigure=N.Figure)
    root.ClassMap = D(Artwork=D(O=N.Layout, Placement=N.Block))
    document = pdf.make_indirect(D(Type=N.StructElem, S=N.Document, P=root))
    root.K = document
    def tag(role, page=None, kids=None, parent=document, **props):
        node = pdf.make_indirect(D(Type=N.StructElem, S=N('/'+role), P=parent, **props))
        if page is not None:
            node.Pg = page.obj
        if kids is not None:
            node.K = kids
        return node
    h = tag('H1', p1, 0, T=S('Document heading'))
    para = tag('P', p1, 1)
    fig = tag('CustomFigure', p1, 2, Alt=S('Blue rectangle labeled A tagged illustration.'), ID=S('figure-1'), E=S('Example figure'), C=N.Artwork, A=D(O=N.Layout, BBox=A([54,420,294,620])))
    multi = tag('P', kids=A([D(Type=N.MCR, Pg=p1.obj, MCID=3), D(Type=N.MCR, Pg=p2.obj, MCID=0)]))
    form_tag = tag('Span', p1, D(Type=N.MCR, Pg=p1.obj, Stm=form, MCID=0))
    table = tag('Table', p2)
    row1 = tag('TR', parent=table)
    row2 = tag('TR', parent=table)
    cells = [tag('TH', kids=1, parent=row1), tag('TH', kids=2, parent=row1), tag('TD', kids=3, parent=row2), tag('TD', kids=4, parent=row2)]
    row1.K, row2.K = A(cells[:2]), A(cells[2:])
    table.K = A([row1, row2])
    annotation = pdf.make_indirect(D(Type=N.Annot, Subtype=N.Link, Rect=A([54,535,130,555]), Border=A([0,0,0]), P=p2.obj, StructParent=2, A=D(S=N.URI, URI=S('https://example.com')), Contents=S('Example website')))
    p2.obj.Annots = A([annotation])
    link = tag('Link', p2, A([5, D(Type=N.OBJR, Obj=annotation)]), Alt=S('Visit the example website'))
    empty = tag('Figure', p2, T=S('Figure without alternate text'))
    document.K = A([h, para, fig, multi, form_tag, table, link, empty])
    p1.obj.StructParents, p2.obj.StructParents = 0, 1
    form.StructParents = 3
    root.ParentTree = pdf.make_indirect(D(Nums=A([0,A([h,para,fig,multi]),1,A([multi,*cells,link]),2,link,3,A([form_tag])])))
    root.ParentTreeNextKey = 4
    root.IDTree = D(Names=A([S('figure-1'), fig]))
    pdf.save(path)
    pdf.close()


if __name__ == '__main__':
    make_demo(Path(__file__).with_name('demo_tagged.pdf'))
