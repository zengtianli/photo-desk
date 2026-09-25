"""Drift guard for LibraryFingerprint (Sources/Models.swift).

Runs one journey-snapshot from engine source against a Photos library READ-ONLY, with a
throwaway data root, records every SQL statement the engine (osxphotos) runs on Photos.sqlite,
and fails if the engine reads a table or column that the fingerprint neither covers nor lists
below as deliberately ignored. Run it after upgrading osxphotos or changing what journey.py uses:

    uv run python tests/fingerprint_coverage.py [path/to/Library.photoslibrary]

Without a path it uses the library Photos last opened. Nothing is written to the library.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

# Read by osxphotos at load time, but behind properties the engine never uses.
IGNORED_TABLES = {
    'ZCOMPUTEDASSETATTRIBUTES': 'PhotoInfo.score (aesthetic scores)',
    'ZEXTENDEDATTRIBUTES': 'PhotoInfo.exif_info',
    'ZCLOUDSHAREDCOMMENT': 'PhotoInfo.comments / likes',
    'ZCLOUDSHAREDALBUMINVITATIONRECORD': 'shared album participant names',
    'ZMOMENT': 'PhotoInfo.moment_info',
}
IGNORED_COLUMNS = {
    'ZASSET': {'ZOVERALLAESTHETICSCORE': 'score', 'ZCURATIONSCORE': 'score', 'ZPROMOTIONSCORE': 'score',
               'ZHIGHLIGHTVISIBILITYSCORE': 'score', 'ZMOMENT': 'moment_info', 'ZIMPORTSESSION': 'import_info'},
    'ZPERSON': {'ZFACECOUNT': 'person_info', 'ZKEYFACE': 'person_info', 'ZMANUALORDER': 'person_info'},
    'ZGENERICALBUM': {c: 'album dates and sort order' for c in
                      ('ZCREATIONDATE', 'ZSTARTDATE', 'ZENDDATE', 'ZCUSTOMSORTASCENDING', 'ZCUSTOMSORTKEY',
                       'ZCLOUDOWNERFULLNAME')},
    'ZSHARE': {c: 'share dates and sort order' for c in
               ('ZCREATIONDATE', 'ZSTARTDATE', 'ZENDDATE', 'ZCUSTOMSORTASCENDING', 'ZCUSTOMSORTKEY')},
    'ZDETECTEDFACE': 'face_info: every column except the asset/person links',
}
ALWAYS = {'sqlite_master', 'Z_METADATA'}


def fingerprint_spec():
    source = (ROOT / 'Sources/Models.swift').read_text()
    body = source[source.index('enum LibraryFingerprint'):source.index('struct LibraryBaseline')]
    lists = {name: re.findall(r'"(Z\w*)"', block) for name, block in
             re.findall(r'static let (\w+) = \[(.*?)\]\n', body, re.S)}
    spec = {}
    for table, columns in re.findall(r'\("(Z\w+)", (\w+|\[[^\]]*\])', body):
        spec[table] = set(lists[columns] if columns in lists else re.findall(r'"(Z\w*)"', columns))
    return spec


def traced_reads(library):
    statements = []
    original = sqlite3.connect

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        target = str(args[0] if args else kwargs.get('database'))
        if 'Photos.sqlite' in target:
            if 'mode=ro' not in target:
                raise AssertionError(f'engine opened the library writable: {target}')
            connection.set_trace_callback(statements.append)
        return connection

    sqlite3.connect = connect
    with tempfile.TemporaryDirectory() as data_root:
        os.environ['PHOTODESK_DATA_ROOT'] = data_root
        sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'vendor')]
        import bridge
        import journey
        request = {'command': 'journey-snapshot', 'library': library or '', 'limit': 1,
                   'options': {'recognize_content': False}}
        result = journey.run(request, cfg=bridge.config(request), api=bridge)
    sqlite3.connect = original
    reads = {}
    for sql in statements:
        text = re.sub(r'--[^\n]*', ' ', sql)
        for table, column in re.findall(r'\b(Z\w+|Z_\w+)\.(\*|Z\w+|Z_\w+)', text):
            reads.setdefault(table, set()).add(column)
        single = re.fullmatch(r'\s*SELECT\s+(.*?)\s+FROM\s+(Z\w+)\s*', text, re.S | re.I)
        if single and '.' not in single.group(1):
            reads.setdefault(single.group(2), set()).update(c.strip().split()[0] for c in single.group(1).split(','))
        for table in re.findall(r'\bFROM\s+(\w+)|\bJOIN\s+(\w+)', text):
            reads.setdefault(next(t for t in table if t), set())
    return result['library'], reads


def main():
    library = sys.argv[1] if len(sys.argv) > 1 else None
    spec = fingerprint_spec()
    used, reads = traced_reads(library)
    problems = []
    for table, columns in sorted(reads.items()):
        if table in ALWAYS or table in IGNORED_TABLES:
            continue
        if re.fullmatch(r'Z_\d+(ASSETS|KEYWORDS)', table):
            continue  # join tables: resolved and hashed whole (minus Z_FOK_ sort keys)
        if table not in spec:
            problems.append(f'{table}: read by the engine, not in LibraryFingerprint.tables')
            continue
        ignored = IGNORED_COLUMNS.get(table, {})
        for column in sorted(columns - spec[table] - {'*'}):
            if isinstance(ignored, str) or column in ignored:
                continue
            problems.append(f'{table}.{column}: read by the engine, not in the fingerprint')
    print(f'library: {used}')
    print(f'tables read: {len(reads)}; fingerprint tables: {len(spec)}')
    if problems:
        print('\n'.join(problems))
        raise SystemExit(1)
    print('fingerprint covers every table and column the engine reads (or lists why it ignores them)')


if __name__ == '__main__':
    main()
