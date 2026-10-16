#!/usr/bin/env python3
"""
test_jurisdiction_prune.py

A jurisdiction page the generator no longer writes is removed from the
state's folder on the next run, unless so many are unwritten at once that the
run itself is the likelier fault.

Stdlib only.  Run:  python -m unittest test_jurisdiction_prune
"""
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # gen-jurisdiction-pages.py imports dd_classify
_SPEC = importlib.util.spec_from_file_location("gen_jurisdiction_pages", os.path.join(HERE, "gen-jurisdiction-pages.py"))
gjp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gjp)


def folder(names):
    path = tempfile.mkdtemp()
    for name in names:
        with open(os.path.join(path, name), "w", encoding="utf-8") as handle:
            handle.write("x")
    return path


class PruneTests(unittest.TestCase):
    def test_pages_no_longer_written_are_removed(self):
        written = {"index.html", "litchfield-county-ct.html", "hartford-county-ct.html"}
        stale = {"litchfieldmsa-1170193032808880-county-ct.html"}
        path = folder(written | stale | {"notes.txt"})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            removed = gjp.prune_stale_pages(path, written)
        self.assertEqual(removed, sorted(stale))
        self.assertEqual(set(os.listdir(path)), written | {"notes.txt"})
        self.assertIn("litchfieldmsa-1170193032808880-county-ct.html", out.getvalue())

    def test_nothing_changes_when_every_page_was_written(self):
        written = {"index.html", "a.html"}
        path = folder(written)
        self.assertEqual(gjp.prune_stale_pages(path, written), [])
        self.assertEqual(set(os.listdir(path)), written)

    def test_many_unwritten_pages_are_left_with_a_warning(self):
        # A run that wrote only the hub would otherwise empty the folder.
        pages = {"page-%d.html" % n for n in range(40)}
        path = folder(pages | {"index.html"})
        with contextlib.redirect_stderr(io.StringIO()) as err:
            removed = gjp.prune_stale_pages(path, {"index.html"})
        self.assertEqual(removed, [])
        self.assertEqual(len(os.listdir(path)), 41)
        self.assertIn("WARNING", err.getvalue())

    def test_the_limit_grows_with_the_state(self):
        written = {"page-%d.html" % n for n in range(200)}
        five_percent = {"old-%d.html" % n for n in range(10)}
        path = folder(written | five_percent)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(gjp.prune_stale_pages(path, written)), 10)
        path = folder(written | five_percent | {"old-10.html"})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(gjp.prune_stale_pages(path, written), [])


if __name__ == "__main__":
    unittest.main()
