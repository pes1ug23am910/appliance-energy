"""Regression for SQL resources omitted by builds from epoch-zero archives."""
import hashlib
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from azure_lab import build_source_archive


class SourceArchiveTest(unittest.TestCase):
    def test_migration_survives_extraction_with_usable_timestamp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            name = "backend/src/main/resources/db/migration/V1__initial.sql"
            migration = root / name
            migration.parent.mkdir(parents=True)
            sql = b"CREATE TABLE regression_probe (id integer PRIMARY KEY);\n"
            migration.write_bytes(sql)
            os.utime(migration, (0, 0))
            ordinary = root / "backend/pom.xml"
            ordinary.write_bytes(b"<project/>\n")
            ordinary_timestamp = 1577836800
            os.utime(ordinary, (ordinary_timestamp, ordinary_timestamp))
            archive = Path(temporary) / "source.tar.gz"
            manifest = build_source_archive(root, [name, "backend/pom.xml", name], archive)

            with tarfile.open(archive) as package:
                self.assertEqual(2, len(package.getmembers()))
                self.assertGreaterEqual(package.getmember(name).mtime, 315532800)
                self.assertEqual(ordinary_timestamp, package.getmember("backend/pom.xml").mtime)
                extracted = Path(temporary) / "extracted"
                package.extractall(extracted, filter="data")
            self.assertEqual(sql, (extracted / name).read_bytes())
            self.assertGreaterEqual((extracted / name).stat().st_mtime, 315532800)
            self.assertEqual(hashlib.sha256(sql).hexdigest(), manifest[name])


if __name__ == "__main__":
    unittest.main()
