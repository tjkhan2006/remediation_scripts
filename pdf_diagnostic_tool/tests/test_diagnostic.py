import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import pikepdf as p
import diagnostic as d

class DiagnosticTests(unittest.TestCase):
    def make(self, folder, *, linked=True, mcid=True, named=False, form=False, artifact=False, orphan=False):
        doc = p.Pdf.new()
        page = doc.add_blank_page()
        root = doc.make_indirect(p.Dictionary(Type=p.Name.StructTreeRoot))
        tag = doc.make_indirect(p.Dictionary(Type=p.Name.StructElem, S=p.Name.P, P=root, Pg=page.obj, K=0))
        root.K = p.Array([] if orphan else [tag])
        page.obj.StructParents = 0
        props = b'/MCID 0' if mcid else b''
        content = (b'/Artifact' if artifact else b'/P') + b' <<'+props+b'>> BDC (test) Tj EMC'
        if named:
            content = b'/P /TagProps BDC (test) Tj EMC'
            page.obj.Resources = p.Dictionary(Properties=p.Dictionary(TagProps=p.Dictionary(MCID=0)))
        if form:
            stream = doc.make_stream(content)
            stream.Type = p.Name.XObject
            stream.Subtype = p.Name.Form
            stream.BBox = p.Array([0, 0, 100, 100])
            stream.StructParents = 1
            stream.Resources = p.Dictionary()
            page.obj.Resources = p.Dictionary(XObject=p.Dictionary(Fm=stream))
            page.Contents = doc.make_stream(b'/Fm Do /Fm Do')
            tag.K = p.Dictionary(Type=p.Name.MCR, Pg=page.obj, Stm=stream, MCID=0)
            key = 1
        else:
            page.Contents = doc.make_stream(content)
            key = 0
        root.ParentTree = doc.make_indirect(p.Dictionary(Nums=p.Array([key, p.Array([tag if linked else None])])))
        doc.Root.StructTreeRoot = root
        path = Path(folder)/'sample.pdf'
        doc.save(path)
        doc.close()
        return path

    def test_read_only_and_bidirectional_link(self):
        with tempfile.TemporaryDirectory() as f:
            path = self.make(f)
            before = path.read_bytes()
            r = d.inventory(path, True)
            self.assertEqual(r['summary']['association_counts'], {'linked': 1})
            self.assertEqual(r['summary']['reachable_tags'], 1)
            self.assertEqual(before, path.read_bytes())
            self.assertTrue(r['objects'])

    def test_no_mcid_is_not_tag(self):
        with tempfile.TemporaryDirectory() as f:
            r = d.inventory(self.make(f, mcid=False))
            self.assertEqual(r['sequences'][0]['association'], 'no_mcid')

    def test_missing_parent_mapping(self):
        with tempfile.TemporaryDirectory() as f:
            r = d.inventory(self.make(f, linked=False))
            self.assertEqual(r['sequences'][0]['association'], 'missing_parent_tree_entry')

    def test_orphan(self):
        with tempfile.TemporaryDirectory() as f:
            r = d.inventory(self.make(f, orphan=True))
            self.assertEqual(r['sequences'][0]['association'], 'unreachable_parent')

    def test_named_properties(self):
        with tempfile.TemporaryDirectory() as f:
            r = d.inventory(self.make(f, named=True))
            self.assertEqual(r['sequences'][0]['association'], 'linked')
            self.assertEqual(r['sequences'][0]['property_name'], '/TagProps')

    def test_reused_form_has_stream_namespace(self):
        with tempfile.TemporaryDirectory() as f:
            r = d.inventory(self.make(f, form=True))
            self.assertEqual(r['summary']['mcid_occurrences'], 1)
            self.assertEqual(r['sequences'][0]['association'], 'linked')
            self.assertEqual(len(r['pages'][0]['form_reuses']), 1)

    def test_artifact_context_logged(self):
        with tempfile.TemporaryDirectory() as f:
            r = d.inventory(self.make(f, artifact=True))
            self.assertIn('mcid_in_artifact_context', r['summary']['issue_counts'])

    def test_id_alias_and_missing_id(self):
        with tempfile.TemporaryDirectory() as f:
            path = self.make(f)
            with p.open(path) as doc:
                root = doc.Root.StructTreeRoot
                tag = root.K[0]
                tag.ID = p.String('current')
                root.IDTree = p.Dictionary(Names=p.Array([p.String('old'), tag]))
                second = Path(f)/'ids.pdf'
                doc.save(second)
            r = d.inventory(second)
            self.assertEqual(r['summary']['id_states'], {'stale_alias': 1})
            self.assertIn('structure_id_lookup_mismatch', r['summary']['issue_counts'])

    def test_compare_and_html(self):
        with tempfile.TemporaryDirectory() as f:
            a = d.inventory(self.make(f))
            self.assertEqual(d.compare(a, a)['changes'], {})
            b = json.loads(json.dumps(a))
            b['sequences'][0]['mcid'] = 5
            diff = d.compare(a, b)
            self.assertIn('sequences', diff['changes'])
            d.report(a, Path(f)/'report.html')
            self.assertIn('Full evidence', (Path(f)/'report.html').read_text())

if __name__ == '__main__':
    unittest.main()
