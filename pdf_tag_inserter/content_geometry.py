from collections import defaultdict
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdftypes import resolve1, dict_value, stream_value
from pdfminer.psparser import PSLiteral, literal_name

class TaggedDevice(PDFPageAggregator):
    """Associate PDFMiner geometry with scoped MCIDs, including nested Form XObjects."""
    def __init__(self, manager):
        super().__init__(manager, laparams=None)
        self.stream_id = 0
        self.marks = []
        self.geometry = defaultdict(list)
        self.text = defaultdict(list)
        self.colors = defaultdict(set)

    def begin_tag(self, tag, props=None):
        props = resolve1(props)
        mcid = props.get('MCID') if isinstance(props, dict) else None
        mcid = resolve1(mcid)
        self.marks.append((self.stream_id, mcid) if isinstance(mcid, int) else None)

    def end_tag(self):
        if self.marks:
            self.marks.pop()

    def capture(self, obj, gstate=None):
        for key in set(k for k in self.marks if k is not None):
            self.geometry[key].append(tuple(obj.bbox))
            state = gstate or getattr(obj, 'graphicstate', None)
            if state is not None:
                self.colors[key].add(f'Fill: {state.ncs.name} {state.ncolor} | Stroke: {state.scs.name} {state.scolor} | Intent: {literal_name(state.intent) if isinstance(state.intent, PSLiteral) else "not explicitly set"}')
            if hasattr(obj, 'stream'):
                self.colors[key].add(f'Image color space: {obj.stream.get("ColorSpace", "not specified / image mask")} | Intent: {obj.stream.get("Intent", "not explicitly set")}')
            if hasattr(obj, 'get_text'):
                self.text[key].append(obj.get_text())

    def render_char(self, *args, **kwargs):
        result = super().render_char(*args, **kwargs)
        self.capture(self.cur_item._objs[-1])
        return result

    def render_image(self, *args, **kwargs):
        super().render_image(*args, **kwargs)
        self.capture(self.cur_item._objs[-1])

    def paint_path(self, *args, **kwargs):
        start = len(self.cur_item._objs)
        super().paint_path(*args, **kwargs)
        for obj in self.cur_item._objs[start:]:
            self.capture(obj, args[0] if args else kwargs.get("gstate"))


class TaggedInterpreter(PDFPageInterpreter):
    def do_BDC(self, tag, props):
        if isinstance(props, PSLiteral):
            props = dict_value(self.resources.get('Properties', {})).get(literal_name(props))
        super().do_BDC(tag, resolve1(props))

    def do_Do(self, xobjid):
        obj = self.xobjmap.get(literal_name(xobjid))
        stream = stream_value(obj) if obj is not None else None
        is_form = stream is not None and stream.get('Subtype') is not None and literal_name(stream.get('Subtype')) == 'Form'
        old_stream, old_marks = self.device.stream_id, self.device.marks[:]
        if is_form:
            self.device.stream_id = stream.objid or 0
        try:
            super().do_Do(xobjid)
        finally:
            self.device.stream_id, self.device.marks = old_stream, old_marks


def display_rect(rect, crop, rotation, size):
    """PDF user space -> rotated, cropped display points, including UserUnit scaling."""
    x0, y0, x1, y1 = crop
    points = []
    for x, y in ((rect[0], rect[1]), (rect[0], rect[3]), (rect[2], rect[1]), (rect[2], rect[3])):
        u, v = (x-x0)/(x1-x0), (y1-y)/(y1-y0)
        if rotation == 90:
            u, v = 1-v, u
        elif rotation == 180:
            u, v = 1-u, 1-v
        elif rotation == 270:
            u, v = v, 1-u
        points.append((u*size[0], v*size[1]))
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))

