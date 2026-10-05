import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.shared.s3 import SEND_FILE_NAMESPACES, s3_delete_all, s3_delete


class TestFileRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bucket = Path(self.tmp.name)
        self.cutoff = time.time() - 90 * 86400

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, key, old=True):
        path = self.bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'disposable fixture')
        if old:
            os.utime(path, (self.cutoff-100, self.cutoff-100))
        return path

    def test_all_send_namespaces_preserved_regardless_of_age(self):
        paths = [self.file(name+'/nested/file') for name in SEND_FILE_NAMESPACES]
        result = s3_delete_all(str(self.bucket), self.cutoff)
        self.assertEqual(result['protected'], len(paths))
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(result['deleted'], 0)

    def test_both_campaign_and_transactional_templates_preserved(self):
        paths = [self.file('templates/'+kind+'/body.html') for kind in ('camp','txn')]
        s3_delete_all(str(self.bucket),self.cutoff)
        self.assertTrue(all(p.exists() for p in paths))

    def test_existing_non_send_retention_still_applies(self):
        old=self.file('exports/old.zip'); recent=self.file('exports/new.zip',False)
        result=s3_delete_all(str(self.bucket),self.cutoff)
        self.assertFalse(old.exists()); self.assertTrue(recent.exists())
        self.assertEqual(result['deleted'],1)

    def test_exact_namespace_boundary(self):
        protected=self.file('lists/a.blk'); old=self.file('lists-old/a.blk')
        s3_delete_all(str(self.bucket),self.cutoff)
        self.assertTrue(protected.exists()); self.assertFalse(old.exists())

    def test_dry_run_never_deletes(self):
        old=self.file('exports/a'); protected=self.file('lists/a')
        result=s3_delete_all(str(self.bucket),self.cutoff,dry_run=True)
        self.assertTrue(old.exists() and protected.exists())
        self.assertEqual(result['old_candidates'],1)
        self.assertEqual(result['deleted'],0)
        self.assertEqual(result['protected_bytes'],protected.stat().st_size)

    def test_file_budget_explicitly_reports_partial_scan(self):
        for n in range(5): self.file('exports/'+str(n))
        result=s3_delete_all(str(self.bucket),self.cutoff,dry_run=True,limit=2)
        self.assertEqual(result['scanned'],2)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(list(self.bucket.rglob('*'))),6)

    def test_directory_budget_handles_empty_trees(self):
        for n in range(5): (self.bucket/str(n)).mkdir()
        self.assertTrue(s3_delete_all(str(self.bucket),self.cutoff,limit=2)['truncated'])

    def test_symlinks_not_followed_or_deleted(self):
        with tempfile.TemporaryDirectory() as other:
            outside=Path(other)/'keep'; outside.write_bytes(b'keep')
            os.utime(outside,(self.cutoff-100,self.cutoff-100))
            (self.bucket/'dir').symlink_to(other,target_is_directory=True)
            (self.bucket/'file').symlink_to(outside)
            result=s3_delete_all(str(self.bucket),self.cutoff)
            self.assertTrue(outside.exists()); self.assertTrue((self.bucket/'file').is_symlink())
            self.assertEqual(result['deleted'],0)

    def test_missing_bucket_and_invalid_budget(self):
        self.assertEqual(s3_delete_all(str(self.bucket/'missing'),self.cutoff)['errors'],1)
        for limit in (0,1000001):
            with self.assertRaises(ValueError): s3_delete_all(str(self.bucket),self.cutoff,limit=limit)

    def test_consumer_owned_delete_unchanged(self):
        path=self.file('sessend/finished.html')
        s3_delete(str(self.bucket),'sessend/finished.html')
        self.assertFalse(path.exists())

    def test_concurrent_creation_of_old_send_files_is_safe(self):
        errors=[]
        def write():
            try:
                for n in range(100): self.file('lists/batch/'+str(n))
            except Exception as exc: errors.append(exc)
        worker=threading.Thread(target=write); worker.start()
        for _ in range(20): s3_delete_all(str(self.bucket),self.cutoff)
        worker.join()
        self.assertEqual(errors,[])
        self.assertEqual(len(list((self.bucket/'lists/batch').iterdir())),100)
