"""Optional bibliographic metadata for Physics Pulse 0.4.1.

The count table and synchronization markers are never changed here. Legacy
metadata is read locally and read-only. Abstracts are stored gzip-compressed
only when restored from a pre-existing legacy database, never downloaded here.
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

LOG = logging.getLogger('physics-pulse-lite')
MAX_ABSTRACT_BYTES = 4 * 1024 * 1024


def initialize(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS paper_details (
        id TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
        title TEXT, authors TEXT, abstract_gz BLOB,
        info_source TEXT NOT NULL DEFAULT 'legacy-local'
    ) WITHOUT ROWID''')


def text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    return value or None


def authors_text(value: Any) -> str | None:
    """Keep the original author order and raw strings; never split commas.

    The earlier collector stored arXivRaw's free-form authors string inside a
    JSON list. Commas can belong to affiliations or collaborations, so parsing
    it into guessed individuals would be misleading.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return text(value)
        value = parsed
    if isinstance(value, list):
        return text('; '.join(v for v in value if isinstance(v, str) and v.strip()))
    return text(value)


def store_observed(db: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Retain titles/authors already received during the ordinary sync.

    No abstract is accepted by this function. Missing fields never erase
    restored fields. Normal metadata updates can replace a cached title/author.
    """
    authors = authors_text(record.get('authors'))
    title = text(record.get('title'))
    if not authors and not title:
        return
    db.execute('''INSERT INTO paper_details(id,title,authors,info_source)
        VALUES (?,?,?,'oai') ON CONFLICT(id) DO UPDATE SET
        title=COALESCE(excluded.title,paper_details.title),
        authors=COALESCE(excluded.authors,paper_details.authors),
        info_source='oai' ''', (record['id'], title, authors))


def unpack_abstract(value: bytes | None) -> str | None:
    if value is None:
        return None
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(value)) as f:
        raw = f.read(MAX_ABSTRACT_BYTES + 1)
    if len(raw) > MAX_ABSTRACT_BYTES:
        raise ValueError('Saved abstract exceeds the safety limit.')
    return raw.decode('utf-8')


def restore_legacy(db: sqlite3.Connection, path: Path) -> dict[str, Any]:
    """Fill metadata gaps only for IDs that already exist in the count DB.

    Safe to rerun. Missing source is not an error and never starts a download.
    A partially harvested legacy DB is still useful for bibliographic fields;
    its coverage/checkpoint markers are deliberately NOT imported.
    """
    report = {'sourcePresent': path.is_file(), 'sourceRowsRead': 0,
              'matchedIds': 0, 'rowsAddedOrFilled': 0}
    if not path.is_file():
        LOG.warning('Legacy database not found: %s. No download; missing authors/abstracts remain unavailable.', path)
        return report
    src = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    src.row_factory = sqlite3.Row
    try:
        src.execute('PRAGMA query_only=ON')
        src.execute('BEGIN')
        cols = {r['name'] for r in src.execute('PRAGMA table_info(papers)')}
        if not {'id', 'published', 'primary_cat'} <= cols:
            raise ValueError('Unrecognized legacy schema. No metadata has been imported.')
        # Only public bibliographic fields are read, never submitter/contact data.
        fields = ['id'] + [x for x in ('title', 'authors', 'summary', 'abstract') if x in cols]
        cursor = src.execute('SELECT ' + ','.join('"' + x + '"' for x in fields) + ' FROM papers')
        statement = '''INSERT INTO paper_details(id,title,authors,abstract_gz,info_source)
            VALUES (?,?,?,?,'legacy-local') ON CONFLICT(id) DO UPDATE SET
            title=COALESCE(paper_details.title,excluded.title),
            authors=COALESCE(paper_details.authors,excluded.authors),
            abstract_gz=COALESCE(paper_details.abstract_gz,excluded.abstract_gz)
            WHERE (paper_details.title IS NULL AND excluded.title IS NOT NULL)
               OR (paper_details.authors IS NULL AND excluded.authors IS NOT NULL)
               OR (paper_details.abstract_gz IS NULL AND excluded.abstract_gz IS NOT NULL)'''
        with db:
            while batch := cursor.fetchmany(500):
                report['sourceRowsRead'] += len(batch)
                ids = [r['id'] for r in batch]
                placeholders = ','.join('?' for _ in ids)
                existing = {r[0] for r in db.execute('SELECT id FROM papers WHERE id IN (' + placeholders + ')', ids)}
                old = {r['id']: r for r in db.execute('SELECT id,title,authors,abstract_gz FROM paper_details WHERE id IN (' + placeholders + ')', ids)}
                updates = []
                for row in batch:
                    if row['id'] not in existing:
                        continue
                    report['matchedIds'] += 1
                    cached = old.get(row['id'])
                    if cached is not None and all(cached[k] is not None for k in ('title', 'authors', 'abstract_gz')):
                        continue
                    title = text(row['title']) if 'title' in cols else None
                    authors = authors_text(row['authors']) if 'authors' in cols else None
                    abstract = text(row['summary']) if 'summary' in cols else None
                    if not abstract and 'abstract' in cols:
                        abstract = text(row['abstract'])
                    zipped = None
                    if abstract and (cached is None or cached['abstract_gz'] is None):
                        raw = abstract.encode('utf-8')
                        if len(raw) > MAX_ABSTRACT_BYTES:
                            raise ValueError('Legacy abstract too large for ' + row['id'])
                        zipped = gzip.compress(raw, compresslevel=6, mtime=0)
                    if title or authors or zipped:
                        updates.append((row['id'], title, authors, zipped))
                before = db.total_changes
                db.executemany(statement, updates)
                report['rowsAddedOrFilled'] += db.total_changes - before
                if report['sourceRowsRead'] % 25000 == 0:
                    LOG.info('Local metadata scan: %s source rows, %s matching IDs.',
                             f"{report['sourceRowsRead']:,}", f"{report['matchedIds']:,}")
    finally:
        src.close()
    LOG.info('Local metadata restore: %s matching IDs; %s rows added/filled. No requests; source unchanged.',
             f"{report['matchedIds']:,}", f"{report['rowsAddedOrFilled']:,}")
    return report
