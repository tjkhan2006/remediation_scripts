import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import test_diagnostic as fixture
from prepare_cases import prepare
from make_controls import make
import diagnostic as d
import pikepdf as p

class WorkflowTests(unittest.TestCase):
    def test_independent_test_inputs_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as f:
            source = fixture.DiagnosticTests().make(f)
            before = source.read_bytes()
            out = Path(f)/'cases'
            manifest = prepare(source, source, out)
            for case in manifest['cases']:
                self.assertEqual((out/case['before']).read_bytes(), before)
                self.assertEqual(case['result'], 'NOT_RUN')
            with self.assertRaises(FileExistsError): prepare(source, source, out)
            self.assertEqual(source.read_bytes(), before)

    def test_cli_refuses_overwrite_source(self):
        with tempfile.TemporaryDirectory() as f:
            source = fixture.DiagnosticTests().make(f)
            before = source.read_bytes()
            proc = subprocess.run([sys.executable, str(Path(d.__file__)), 'audit', str(source), '--out', str(source)], capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(source.read_bytes(), before)

    def test_structure_cycle_terminates(self):
        with tempfile.TemporaryDirectory() as f:
            source = fixture.DiagnosticTests().make(f)
            with p.open(source) as doc:
                doc.Root.StructTreeRoot.K[0].K = doc.Root.StructTreeRoot.K[0]
                target = Path(f)/'cycle.pdf'
                doc.save(target)
            r = d.inventory(target)
            self.assertEqual(r['summary']['reachable_tags'], 1)
            self.assertIn('structure_cycle_or_shared_kid', r['summary']['issue_counts'])

    def test_control_generation_preserves_october_tree(self):
        with tempfile.TemporaryDirectory() as f:
            source = fixture.DiagnosticTests().make(f)
            with p.open(source) as doc:
                for _ in range(11): doc.add_blank_page()
                target = Path(f)/'twelve.pdf'
                doc.save(target)
            before = target.read_bytes()
            out = Path(f)/'controls'
            records = make(target, target, out)
            self.assertEqual(len(records), 4)
            self.assertEqual(d.inventory(out/'october_resaved.pdf')['summary']['reachable_tags'], 1)
            self.assertEqual(d.inventory(out/'october_base_working_page12.pdf')['summary']['reachable_tags'], 1)
            self.assertEqual(d.inventory(out/'single_october12.pdf')['summary']['reachable_tags'], 0)
            with p.open(out/'october_base_working_page12.pdf') as doc:
                self.assertNotIn('/AF', doc.Root)
                self.assertNotIn('/StructParents', doc.pages[11].obj)
            self.assertEqual(target.read_bytes(), before)

if __name__ == '__main__': unittest.main()
