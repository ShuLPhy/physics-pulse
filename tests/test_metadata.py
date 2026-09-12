"""Offline fixtures only: metadata recovery must not change counts or sync state."""
from pathlib import Path
import gzip
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import update_data as m
import paper_metadata as md
import oai
from test_pipeline import ASOF, Client, rec, page


class TestMetadataRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.dbpath=self.root/'physics-lite.sqlite'
        self.db=m.connect_db(self.dbpath);self.addCleanup(self.db.close)
        self.source=self.root/'arxiv.sqlite';self.site=self.root/'site'
        self.tax=json.loads((ROOT/'scripts/taxonomy.json').read_text())
        self.allowed={x['id'] for x in self.tax['categories']}
        with self.db:
            for pid,date in [('2609.12345','2026-09-03T12:00:00Z'),('2609.12346','2026-09-04T12:00:00Z'),('2201.12345','2022-01-03T12:00:00Z')]:
                m.upsert_records(self.db,[{'id':pid,'created':m.epoch(m.utc_datetime(date)),'category':'cond-mat.dis-nn'}],m.retention_start(ASOF,60),self.allowed)
            for k,v in [('coverage_from',m.stamp(m.retention_start(ASOF,60))),('snapshot_as_of',m.stamp(ASOF)),('last_success',m.stamp(ASOF))]:m.put_meta(self.db,k,v)
        src=sqlite3.connect(self.source)
        src.executescript('CREATE TABLE papers(id TEXT PRIMARY KEY,published TEXT,primary_cat TEXT,title TEXT,authors TEXT,summary TEXT);CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);')
        rows=[('2609.12345','2026-09-03T12:00:00Z','cond-mat.dis-nn','A saved title',json.dumps(['A. Example (Institute A, City B), B. Sample']),'Cyclotron resonance and quantum transport.'),
              ('2609.12346','2026-09-04T12:00:00Z','cond-mat.dis-nn','Second saved title','[]',''),
              ('2201.12345','2022-01-03T12:00:00Z','cond-mat.dis-nn','Older title',json.dumps(['First Author','Second Author']),'Old abstract'),
              ('2609.99999','2026-09-03T12:00:00Z','cond-mat.dis-nn','Not in count cache',json.dumps(['Excluded']),'Not to import')]
        src.executemany('INSERT INTO papers VALUES (?,?,?,?,?,?)',rows)
        src.execute('INSERT INTO meta VALUES (?,?)',('checkpoint',json.dumps({'token':'UNFINISHED-MONTHLY'})))
        src.commit();src.close()
        self.source_before=self.source.read_bytes()
        self.core_before=[tuple(r) for r in self.db.execute('SELECT * FROM papers ORDER BY id')]
        self.meta_before=[tuple(r) for r in self.db.execute('SELECT * FROM meta ORDER BY key')]
    def restore(self):return md.restore_legacy(self.db,self.source)
    def snapshot(self):
        now,n,cov=m.local_coverage(self.db,60)
        return m.aggregate(self.db,self.tax,now,n,cov)
    def details(self,pid='2609.12345'):
        return self.db.execute('SELECT * FROM paper_details WHERE id=?',(pid,)).fetchone()
    def test_counts_and_sync_markers_unchanged(self):
        self.restore()
        self.assertEqual(self.core_before,[tuple(r) for r in self.db.execute('SELECT * FROM papers ORDER BY id')])
        self.assertEqual(self.meta_before,[tuple(r) for r in self.db.execute('SELECT * FROM meta ORDER BY key')])
    def test_old_database_unchanged(self):
        self.restore();self.assertEqual(self.source.read_bytes(),self.source_before)
    def test_no_unknown_ids_added(self):
        report=self.restore();self.assertEqual(report['matchedIds'],3)
        self.assertIsNone(self.details('2609.99999'))
    def test_raw_authors_preserve_order_and_affiliation_commas(self):
        self.restore();self.assertEqual(self.details()['authors'],'A. Example (Institute A, City B), B. Sample')
        self.assertEqual(self.details('2201.12345')['authors'],'First Author; Second Author')
    def test_empty_authors_not_invented(self):
        self.restore();self.assertIsNone(self.details('2609.12346')['authors'])
    def test_abstract_is_compressed(self):
        self.restore();data=self.details()['abstract_gz']
        self.assertTrue(data.startswith(b'\x1f\x8b'))
        self.assertEqual(md.unpack_abstract(data),'Cyclotron resonance and quantum transport.')
    def test_safe_to_repeat(self):
        self.assertEqual(self.restore()['rowsAddedOrFilled'],3)
        self.assertEqual(self.restore()['rowsAddedOrFilled'],0)
    def test_newer_observed_names_not_overwritten_by_old(self):
        with self.db:md.store_observed(self.db,{'id':'2609.12345','title':'Current title','authors':'Current Author','abstract':'DO NOT STORE'})
        self.restore();d=self.details()
        self.assertEqual(d['title'],'Current title');self.assertEqual(d['authors'],'Current Author')
        self.assertIn('Cyclotron',md.unpack_abstract(d['abstract_gz']))
    def test_ordinary_sync_keeps_author_without_new_abstract(self):
        m.harvest(self.db,self.tax,ASOF,60,Client([page([rec()])]))
        d=self.details();self.assertEqual(d['authors'],'FORBIDDEN_AUTHOR_PAYLOAD')
        self.assertIsNone(d['abstract_gz'])
    def test_parser_author_opt_in(self):
        p=oai.parse_oai(page([rec()]),author_minimum=m.retention_start(ASOF,60))['records'][0]
        self.assertIn('authors',p);self.assertNotIn('abstract',p)
        self.assertNotIn('summary',p)
    def test_titles_off_with_author_retention(self):
        p=oai.parse_oai(page([rec()]),None,author_minimum=m.retention_start(ASOF,60))['records'][0]
        self.assertIn('authors',p);self.assertNotIn('title',p)
    def test_counts_only_sync_does_not_add_bibliography(self):
        m.harvest(self.db,self.tax,ASOF,60,Client([page([rec()])]),title_months=0,retain_bibliography=False)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_details').fetchone()[0],0)
    def test_increment_does_not_force_full_window_for_new_fields(self):
        c=Client([page([rec()])]);m.harvest(self.db,self.tax,ASOF,60,c)
        self.assertNotIn('set=physics',c.urls[0]);self.assertIn('from=2026-09-09',c.urls[0])
    def test_old_title_survives_recent_title_pruning(self):
        self.restore();m.publish(self.db,self.snapshot(),self.site)
        snap=json.loads((self.site/'data/physics.json').read_text())
        payload=json.loads(gzip.decompress((self.site/snap['paperFiles']['2022-01-01']['cond-mat.dis-nn']).read_bytes()))
        self.assertEqual(payload['papers'][0][2],'Older title')
    def test_export_fields_and_partial_coverage(self):
        self.restore();snap=self.snapshot();m.publish(self.db,snap,self.site)
        payload=json.loads(gzip.decompress((self.site/snap['paperFiles']['2026-09-01']['cond-mat.dis-nn']).read_bytes()))
        self.assertEqual(payload['schemaVersion'],2)
        self.assertEqual(payload['metadataCoverage'],{'papers':2,'titles':2,'authors':1,'abstracts':1})
        self.assertEqual(snap['metadataTotals'],{'papers':3,'titles':3,'authors':2,'abstracts':2})
    def test_deletion_cascades_details(self):
        self.restore()
        with self.db:m.upsert_records(self.db,[{'id':'2609.12345','deleted':True}],m.retention_start(ASOF,60),self.allowed)
        self.assertIsNone(self.details())
    def test_category_exit_cascades_details(self):
        self.restore()
        with self.db:m.upsert_records(self.db,[{'id':'2609.12345','category':'cs.LG','created':m.epoch(ASOF)}],m.retention_start(ASOF,60),self.allowed)
        self.assertIsNone(self.details())
    def test_missing_legacy_creates_no_empty_db(self):
        missing=self.root/'missing.sqlite'
        self.assertFalse(md.restore_legacy(self.db,missing)['sourcePresent']);self.assertFalse(missing.exists())
    def test_unknown_legacy_schema_is_rejected(self):
        p=self.root/'bad.sqlite';c=sqlite3.connect(p);c.execute('CREATE TABLE foo(x)');c.close()
        with self.assertRaises(ValueError):md.restore_legacy(self.db,p)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_details').fetchone()[0],0)
    def test_local_only_entry_point_never_calls_network(self):
        m.publish(self.db,self.snapshot(),self.site)
        args=['--local-only','--restore-metadata','--db',str(self.dbpath),'--legacy-db',str(self.source),'--site',str(self.site)]
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('NETWORK FORBIDDEN')) as req:
            self.assertEqual(m.main(args),0);req.assert_not_called()
        for key,value in self.meta_before:
            self.assertEqual(json.loads(value),m.get_meta(self.db,key))
    def test_no_legacy_does_not_trigger_network(self):
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('NETWORK FORBIDDEN')) as req:
            self.assertEqual(m.main(['--local-only','--restore-metadata','--db',str(self.dbpath),'--legacy-db',str(self.root/'missing.sqlite'),'--site',str(self.site)]),0)
            req.assert_not_called()
    def test_pending_lite_harvest_refused_without_touching_details(self):
        with self.db:m.put_meta(self.db,'checkpoint',{'token':'PENDING'})
        self.assertEqual(m.main(['--local-only','--restore-metadata','--db',str(self.dbpath),'--legacy-db',str(self.source),'--site',str(self.site)]),1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_details').fetchone()[0],0)
    def test_restore_flag_requires_local_only(self):
        with self.assertRaises(SystemExit):m.main(['--restore-metadata'])
    def test_missing_lite_not_created(self):
        p=self.root/'absent'/'new.sqlite'
        with self.assertRaises(SystemExit):m.main(['--local-only','--restore-metadata','--db',str(p)])
        self.assertFalse(p.exists())
    def test_oversized_gzip_is_rejected(self):
        with patch.object(md,'MAX_ABSTRACT_BYTES',10):
            with self.assertRaises(ValueError):md.unpack_abstract(gzip.compress(b'x'*11))
    def test_json_authors_and_plain_text_accepted(self):
        self.assertEqual(md.authors_text('["A, B","C"]'),'A, B; C')
        self.assertEqual(md.authors_text('Raw author (Affiliation, City)'),'Raw author (Affiliation, City)')
        self.assertIsNone(md.authors_text('[]'))

if __name__=='__main__':unittest.main()
