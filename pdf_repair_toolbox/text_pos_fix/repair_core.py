"""Transactional repair, local rendering, and atomic verified save."""
from io import BytesIO
from pathlib import Path
import os
import tempfile
import pikepdf as q
import pymupdf as fitz
from content_order import analyze, digest

class Document:
    def __init__(self, path, password=''):
        self.path = Path(path).resolve()
        self.password = password
        self.pdf = q.open(self.path, password=password)
        self.original = self.path.read_bytes()
        self.history = []
        self.dirty = False
        self.plans = []
        self.scan()

    def close(self):
        self.pdf.close()

    def snapshot(self):
        out = BytesIO()
        self.pdf.save(out, encryption=True if self.pdf.is_encrypted else None)
        return out.getvalue()

    def scan(self):
        self.plans = [analyze(page) for page in self.pdf.pages]
        return self.plans

    def repair(self, pages=None):
        selected = list(range(len(self.pdf.pages))) if pages is None else sorted(set(pages))
        if any(i < 0 or i >= len(self.pdf.pages) for i in selected):
            raise ValueError('Page number is outside the document.')
        plans = {i: analyze(self.pdf.pages[i]) for i in selected}
        ready = [i for i in selected if plans[i].data is not None]
        if not ready:
            return plans
        before, dirty = self.snapshot(), self.dirty
        try:
            for i in ready:
                page = self.pdf.pages[i]
                page.obj.Contents = self.pdf.make_stream(plans[i].data)
                page.obj.TextPosFixDigest = q.String(digest(page))
            self._verify_geometry(before, self.snapshot(), ready)
        except Exception:
            self.pdf.close()
            self.pdf = q.open(BytesIO(before), password=self.password)
            self.dirty = dirty
            self.scan()
            raise
        self.history.append((before, dirty))
        self.dirty = True
        self.scan()
        return plans

    def _renderer(self, data):
        doc = fitz.open(stream=data, filetype='pdf')
        if doc.needs_pass and not doc.authenticate(self.password):
            doc.close()
            raise ValueError('PDF password was rejected by the preview renderer.')
        return doc

    def _verify_geometry(self, before, after, pages):
        def signatures(page):
            return sorted((tuple(c[0] for c in s['chars']), tuple(round(v, 4) for v in s['bbox']),
                           s['font'], round(s['size'], 4)) for s in page.get_texttrace())
        with self._renderer(before) as old, self._renderer(after) as new:
            if len(old) != len(new):
                raise ValueError('Page count changed; repair was rolled back.')
            for i in pages:
                if old[i].rect != new[i].rect or signatures(old[i]) != signatures(new[i]):
                    raise ValueError(f'Text geometry verification failed on page {i+1}; repair was rolled back.')

    def undo(self):
        if not self.history:
            return
        before, dirty = self.history.pop()
        self.pdf.close()
        self.pdf = q.open(BytesIO(before), password=self.password)
        self.dirty = dirty
        self.scan()

    def render(self, page, scale=1, original=False):
        with self._renderer(self.original if original else self.snapshot()) as doc:
            pix = doc[page].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return pix.width, pix.height, pix.samples

    def text_items(self, page):
        with self._renderer(self.snapshot()) as doc:
            # Includes covered and invisible text; extraction does not perform OCR.
            return [{'text': ''.join(chr(c[0]) for c in span['chars']), 'bbox': span['bbox'],
                     'font': span['font'], 'size': span['size'], 'type': span['type']}
                    for span in doc[page].get_texttrace()]

    def save(self, path):
        target = Path(path).resolve()
        if target == self.path or (target.exists() and os.path.samefile(target, self.path)):
            raise ValueError('Choose a different filename from the source PDF.')
        fd, temp = tempfile.mkstemp(prefix='.text-pos-fix-', suffix='.pdf', dir=target.parent)
        os.close(fd)
        try:
            self.pdf.save(temp, encryption=True if self.pdf.is_encrypted else None)
            with q.open(temp, password=self.password) as saved:
                if len(saved.pages) != len(self.pdf.pages) or saved.check_pdf_syntax():
                    raise ValueError('Saved PDF failed structural verification.')
            self._verify_geometry(self.snapshot(), Path(temp).read_bytes(), range(len(self.pdf.pages)))
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.dirty = False
