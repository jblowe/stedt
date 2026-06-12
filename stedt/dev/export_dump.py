#!/usr/bin/env python3
"""Export stedt.sqlite back to the original MySQL dump format.

The inverse of stedt.dev.build_db, for releasing a post-revival public dump or feeding
the original rootcanal stack (which wants MySQL): emits DROP/CREATE/INSERT statements in
the exact shape of STEDT_public_20160602.sql. The DDL is copied VERBATIM from a reference
dump (so the schema is rootcanal's own, not a reconstruction); each table's rows are
emitted full-width in the dump's column order — build_db.TABLES, the single proven map of
that order — with single-line multi-row INSERTs, which is also what build_db's own parser
reads, so the round trip is self-testable:

    stedt dump export out.sql
    STEDT_ROOT=/tmp/x python -m stedt.dev.build_db out.sql   # parse it back
    (then compare shared columns per table against the source stedt.sqlite)

Columns the all-TSV migration deliberately dropped (modtime/datetime, uid, refcount,
seqlocked, lexicon.chapter, chapters' fascicle counters) can't be recovered; they're
emitted as documented constants below — uid as 8, rootcanal's canonical 'stedt' curator
(for lx_et_hash this is exact: only uid-8 taggings were kept), timestamps as the DDL's
zero default. The emitted file is MySQL-compatible and semantically faithful, NOT
byte-identical to a live mysqldump.

Args: [dest.sql] [--ddl-from reference_dump.sql]
"""

import argparse
import os
import re
import sqlite3

from stedt.paths import DB, ROOT
from stedt.dev.build_db import PK, SQLDUMP, TABLES

# constants for columns that exist in the dump schema but not in the migrated data
ZEROTIME = "0000-00-00 00:00:00"  # the DDL's own timestamp default
STEDT_UID = 8                     # rootcanal's canonical 'stedt' curator id
DEFAULTS = {
    ("etyma", "modtime"): ZEROTIME,
    ("etyma", "uid"): STEDT_UID,
    ("etyma", "refcount"): None,   # nullable in the DDL; real counts not preserved
    ("etyma", "seqlocked"): 0,
    ("lexicon", "chapter"): "",
    ("lexicon", "modtime"): ZEROTIME,
    ("lx_et_hash", "uid"): STEDT_UID,  # exact: only the uid-8 (stedt) taggings were migrated
    ("languagenames", "modtime"): ZEROTIME,
    ("chapters", "v"): 0, ("chapters", "f"): 0, ("chapters", "c"): 0,
    ("chapters", "s1"): 0, ("chapters", "s2"): 0, ("chapters", "s3"): 0,
    ("notes", "datetime"): ZEROTIME,
    ("notes", "uid"): STEDT_UID,
    ("mesoroots", "uid"): STEDT_UID,
    ("glosswords", "modtime"): ZEROTIME,
    ("hptb", "modtime"): ZEROTIME,
}

CHUNK = 800  # rows per INSERT statement (mysqldump-style multi-row lines)


def _esc(v):
    # type-driven, like mysqldump: numerics unquoted (incl. decimals — etyma.sequence),
    # NULL bare, strings quoted with backslash escapes (the importer's decode() inverse)
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    s = s.replace("\\", "\\\\").replace("'", "\\'")
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\0", "\\0").replace("\x1a", "\\Z")
    return f"'{s}'"


def _ddl_blocks(ref_path, tables):
    """Verbatim per-table DDL from the reference dump: the comment banner + DROP + CREATE
    (+ the charset guard lines mysqldump wraps them in), keyed by table name."""
    src = open(ref_path, encoding="utf-8", errors="replace").read()
    out = {}
    for t in tables:
        m = re.search(
            r"--\n-- Table structure for table `" + re.escape(t) + r"`\n--\n\n"
            r".*?/\*!40101 SET character_set_client = @saved_cs_client \*/;",
            src,
            re.S,
        )
        if not m:
            raise SystemExit(f"dump export: no CREATE TABLE block for `{t}` in {ref_path}")
        out[t] = m.group(0)
    # the dump's own global preamble (everything before the first table banner)
    preamble = src[: src.index("--\n-- Table structure for table")]
    # and its tail of session-restore statements
    tail = src[src.rindex("/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;") :]
    return preamble, out, tail


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dest", nargs="?", default=os.path.join(ROOT, "stedt_export.sql"))
    ap.add_argument("--ddl-from", default=SQLDUMP,
                    help="reference dump supplying the verbatim DDL (default: the stock 2016 dump)")
    args = ap.parse_args()
    if not os.path.exists(DB):
        raise SystemExit("dump export: build stedt.sqlite first (stedt build db)")

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    have = {t: [r[1] for r in db.execute(f"PRAGMA table_info({t})")] for t in TABLES}
    preamble, ddl, tail = _ddl_blocks(args.ddl_from, TABLES)

    n_rows = {}
    with open(args.dest, "w", encoding="utf-8") as f:
        f.write(preamble)
        f.write(
            "--\n-- Re-exported from the STEDT revival's all-TSV data "
            "(stedt dump export).\n"
            "-- Columns not preserved by the migration are constants: uid=8 ('stedt'; exact\n"
            "-- for lx_et_hash), timestamps '0000-00-00 00:00:00', refcount NULL, "
            "seqlocked 0,\n-- lexicon.chapter '', chapters fascicle counters 0.\n--\n\n"
        )
        for t, cols in TABLES.items():
            f.write(ddl[t] + "\n\n--\n-- Dumping data for table `" + t + "`\n--\n\n")
            f.write(f"LOCK TABLES `{t}` WRITE;\n")
            f.write(f"/*!40000 ALTER TABLE `{t}` DISABLE KEYS */;\n")
            present = [c for c in cols if c in have[t]]
            sel = ", ".join(present)
            order = f" ORDER BY {PK[t]}" if t in PK and PK[t] in have[t] else ""
            buf = []
            n = 0
            for row in db.execute(f"SELECT {sel} FROM {t}{order}"):
                byname = dict(zip(present, row))
                vals = []
                for c in cols:
                    v = byname[c] if c in byname else DEFAULTS[(t, c)]
                    vals.append(_esc(v))
                buf.append("(" + ",".join(vals) + ")")
                n += 1
                if len(buf) >= CHUNK:
                    f.write(f"INSERT INTO `{t}` VALUES {','.join(buf)};\n")
                    buf = []
            if buf:
                f.write(f"INSERT INTO `{t}` VALUES {','.join(buf)};\n")
            f.write(f"/*!40000 ALTER TABLE `{t}` ENABLE KEYS */;\nUNLOCK TABLES;\n\n")
            n_rows[t] = n
        f.write(tail)

    total = sum(n_rows.values())
    print(f"{args.dest}: {total:,} rows across {len(TABLES)} tables "
          f"({os.path.getsize(args.dest)/1e6:.1f} MB)")
    print("note: tables not held by the migrated data (changelog, users, etyma_scratch, "
          "etymologies, morphemes, …) are not emitted — source those from the stock dump "
          "if rootcanal needs them.")


if __name__ == "__main__":
    main()
