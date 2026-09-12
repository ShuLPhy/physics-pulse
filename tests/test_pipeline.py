"""Synthetic-only tests of the lean storage, monthly calculations, and migration."""
from pathlib import Path
import sys,tempfile,unittest,json,gzip,sqlite3
from datetime import datetime,timezone,timedelta
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import update_data as m
import oai
OAI=oai.OAI_NS;RAW='{http://arxiv.org/OAI/arXivRaw/}'
ASOF=m.utc_datetime('2026-09-11T17:00:00Z')


def rec(id='2609.12345',date='2026-09-03T12:00:00Z',cats='cond-mat.dis-nn cond-mat.stat-mech',title='Disorder and quantum transport'):
    return {'id':id,'date':date,'cats':cats,'title':title}


def page(records,token=None,error=None):
    root=ET.Element(OAI+'OAI-PMH');ET.SubElement(root,OAI+'responseDate').text=m.stamp(ASOF)
    if error:
        ET.SubElement(root,OAI+'error',code=error).text='fixture error';return ET.tostring(root)
    listing=ET.SubElement(root,OAI+'ListRecords')
    for p in records:
        record=ET.SubElement(listing,OAI+'record');h=ET.SubElement(record,OAI+'header',{'status':'deleted'} if p.get('deleted') else {})
        ET.SubElement(h,OAI+'identifier').text='oai:arXiv.org:'+p['id']
        if p.get('deleted'):continue
        ET.SubElement(h,OAI+'datestamp').text='2026-09-11'
        raw=ET.SubElement(ET.SubElement(record,OAI+'metadata'),RAW+'arXivRaw')
        ET.SubElement(raw,RAW+'id').text=p['id']
        for v,date in [('v1',p['date']),('v2','2026-09-10T20:00:00Z')]:ET.SubElement(ET.SubElement(raw,RAW+'version',version=v),RAW+'date').text=date
        ET.SubElement(raw,RAW+'categories').text=p['cats'];ET.SubElement(raw,RAW+'title').text=p['title']
        ET.SubElement(raw,RAW+'authors').text='FORBIDDEN_AUTHOR_PAYLOAD'
        ET.SubElement(raw,RAW+'abstract').text='FORBIDDEN_ABSTRACT_PAYLOAD'*1000
    ET.SubElement(listing,OAI+'resumptionToken').text=token
    return ET.tostring(root)


class Client:
    def __init__(self,responses):self.responses=iter(responses);self.urls=[]
    def request(self,url,**kwargs):self.urls.append(url);return next(self.responses)


class TestParser(unittest.TestCase):
    def test_only_three_default_fields(self):
        p=oai.parse_oai(page([rec()]))['records'][0]
        self.assertEqual(set(p),{'id','created','category'})
        self.assertEqual(p['created'],m.epoch(m.utc_datetime('2026-09-03T12:00:00Z')))
    def test_recent_title_only(self):
        p=oai.parse_oai(page([rec(),rec('2109.12345','2021-09-02T00:00:00Z')]),m.shift_month(ASOF,-1))['records']
        self.assertIn('title',p[0]);self.assertNotIn('title',p[1])
    def test_payload_does_not_escape_parser(self):
        text=json.dumps(oai.parse_oai(page([rec()]),m.shift_month(ASOF,-1)))
        self.assertNotIn('FORBIDDEN',text);self.assertNotIn('authors',text);self.assertNotIn('abstract',text)
    def test_v1_not_v2(self):
        p=oai.parse_oai(page([rec()]))['records'][0];self.assertEqual(datetime.fromtimestamp(p['created'],timezone.utc).day,3)
    def test_primary_not_crosslist(self):
        self.assertEqual(oai.parse_oai(page([rec()]))['records'][0]['category'],'cond-mat.dis-nn')
    def test_alias(self):
        self.assertEqual(oai.parse_oai(page([rec(cats='math.MP math-ph')]))['records'][0]['category'],'math-ph')
    def test_deleted(self):self.assertTrue(oai.parse_oai(page([{'id':'2609.12345','deleted':True}]))['records'][0]['deleted'])
    def test_errors_are_not_zero(self):
        with self.assertRaises(oai.OAIError):oai.parse_oai(page([],error='badArgument'))
    def test_no_records_match(self):self.assertEqual(oai.parse_oai(page([],error='noRecordsMatch'))['records'],[])
    def test_missing_v1_fails(self):
        with self.assertRaises(oai.HarvestError):oai.parse_oai(page([rec()]).replace(b'version="v1"',b'version="v3"'))
    def test_reject_html_dtd_and_bad_xml(self):
        for body in [b'<html>x</html>',b'<!DOCTYPE x><x/>',b'<x>']:
            with self.assertRaises(oai.HarvestError):oai.parse_oai(body)
    def test_explicit_timezone(self):
        with self.assertRaises(ValueError):m.utc_datetime('2026-09-01T00:00:00')
    def test_minimum_request_interval(self):self.assertEqual(oai.SerialHTTP('test',minimum_interval=.1).minimum_interval,3.1)


class TestLite(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.site=self.root/'site'
        self.db=m.connect_db(self.root/'lite.sqlite');self.addCleanup(self.db.close)
        self.tax=json.loads((ROOT/'scripts/taxonomy.json').read_text());self.allowed={c['id'] for c in self.tax['categories']}
        self.minimum=m.retention_start(ASOF,60);self.coverage={'complete':True,'from':m.stamp(self.minimum),'to':m.stamp(ASOF)}
    def insert(self,*records,title_months=2):
        titlemin=m.shift_month(ASOF,1-title_months) if title_months else None
        with self.db:m.upsert_records(self.db,oai.parse_oai(page(records),titlemin)['records'],self.minimum,self.allowed,titlemin)
    def agg(self,asof=ASOF,months=60,**kwargs):return m.aggregate(self.db,self.tax,asof,months,{**self.coverage,'to':m.stamp(asof)},**kwargs)
    def cat(self,d,id='cond-mat.dis-nn'):return next(c for c in d['categories'] if c['id']==id)
    def test_schema_has_no_bulky_fields(self):
        self.assertEqual([r['name'] for r in self.db.execute('PRAGMA table_info(papers)')],['id','created','category'])
        self.assertEqual([r['name'] for r in self.db.execute('PRAGMA table_info(recent_titles)')],['id','title'])
    def test_sixty_calendar_months_and_default_current(self):
        d=self.agg();self.assertEqual(d['monthStarts'][0],'2021-10-01');self.assertEqual(d['monthStarts'][-1],'2026-09-01');self.assertEqual(len(d['monthStarts']),60)
        self.assertEqual((d['defaultMonthIndex'],d['latestCompleteMonthIndex']),(59,58))
    def test_hidden_month_baseline(self):
        self.insert(rec('2109.12345','2021-09-10T00:00:00Z'),rec('2110.12345','2021-10-10T00:00:00Z'))
        c=self.cat(self.agg());self.assertEqual(c['baselinePreviousCount'],1);self.assertEqual(c['counts'][0],1)
    def test_duplicate_versions_and_crosslists(self):
        self.insert(rec());self.insert(rec(title='Changed title'));d=self.agg()
        self.assertEqual(self.cat(d)['counts'][-1],1);self.assertEqual(self.cat(d,'cond-mat.stat-mech')['counts'][-1],0)
    def test_half_open_month_and_cutoffs(self):
        self.insert(rec('2608.12341','2026-08-01T00:00:00Z'),rec('2608.12342','2026-08-11T16:59:59Z'),rec('2608.12343','2026-08-11T17:00:00Z'),rec('2608.12344','2026-08-31T23:59:59Z'),rec('2609.12345','2026-09-01T00:00:00Z'),rec('2609.12346','2026-09-11T16:59:59Z'),rec('2609.12347','2026-09-11T17:00:00Z'))
        c=self.cat(self.agg());self.assertEqual(c['counts'][-2:],[4,2]);self.assertEqual(c['previousComparable'],2);self.assertEqual(c['currentComparable'],2)
    def test_long_month_caps_both_comparisons_not_area(self):
        self.insert(rec('2602.12341','2026-02-28T23:59:59Z'),rec('2603.12342','2026-03-28T23:59:59Z'),rec('2603.12343','2026-03-29T00:00:00Z'),rec('2603.12344','2026-03-30T12:00:00Z'))
        d=self.agg(asof=m.utc_datetime('2026-03-31T12:00:00Z'),months=24);c=self.cat(d)
        self.assertEqual(c['counts'][-1],3);self.assertEqual(c['currentComparable'],1);self.assertEqual(c['previousComparable'],1);self.assertTrue(d['comparison']['cappedToShorterMonth'])
    def test_leap_year(self):self.assertEqual(m.comparison_window(m.utc_datetime('2024-03-31T12:00:00Z'))['commonDurationSeconds'],29*86400)
    def test_month_start_zero_elapsed(self):self.assertEqual(m.comparison_window(m.utc_datetime('2026-09-01T00:00:00Z'))['commonDurationSeconds'],0)
    def test_year_rollover_and_utc(self):
        self.assertEqual(m.stamp(m.shift_month(m.utc_datetime('2026-01-01T00:00:00Z'),-1)),'2025-12-01T00:00:00Z')
        self.assertEqual(m.month_start(m.utc_datetime('2026-09-01T00:30:00+09:00')).month,8)
    def test_reclassification_removes_title_too(self):
        self.insert(rec());self.insert(rec(cats='cs.LG cond-mat.dis-nn'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0],0);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM recent_titles').fetchone()[0],0)
    def test_unknown_physics_category_aborts(self):
        with self.assertRaises(m.HarvestError):self.insert(rec(cats='physics.new-cat'))
    def test_old_submission_with_new_metadata_not_counted(self):
        self.insert(rec(date='2020-01-01T00:00:00Z'));self.assertEqual(sum(self.cat(self.agg())['counts']),0)
    def test_no_old_titles(self):
        self.insert(rec('2607.12345','2026-07-31T23:59:59Z'),rec('2608.12345','2026-08-01T00:00:00Z'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM recent_titles').fetchone()[0],1)
    def test_titles_disabled(self):
        self.insert(rec(),title_months=0);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM recent_titles').fetchone()[0],0)
    def test_incomplete_coverage_rejected(self):
        for cov in [{'complete':False},{**self.coverage,'from':'2026-01-01T00:00:00Z'},{**self.coverage,'to':'2026-09-01T00:00:00Z'}]:
            with self.assertRaises(m.HarvestError):m.aggregate(self.db,self.tax,ASOF,60,cov)
    def test_compact_exports_omit_all_abstracts_and_old_titles(self):
        self.insert(rec(),rec('2201.12345','2022-01-03T00:00:00Z'));d=self.agg();m.publish(self.db,d,self.site)
        for month,nfields in [('2026-09-01',3),('2022-01-01',2)]:
            path=d['paperFiles'][month]['cond-mat.dis-nn'];body=gzip.decompress((self.site/path).read_bytes());payload=json.loads(body)
            self.assertEqual(len(payload['papers'][0]),nfields);self.assertNotIn(b'FORBIDDEN',body)
    def test_counts_only_exports_no_paper_files(self):
        self.insert(rec());d=self.agg(title_months=0,paper_index=False);m.publish(self.db,d,self.site)
        self.assertEqual(d['paperFiles'],{});self.assertFalse((self.site/'data/papers').exists())
    def test_old_public_abstract_files_purged_after_success(self):
        p=self.site/'data/papers/old.json';p.parent.mkdir(parents=True);p.write_text('FORBIDDEN_ABSTRACT_PAYLOAD')
        self.insert(rec());m.publish(self.db,self.agg(),self.site);self.assertFalse(p.exists())
    def test_failed_export_keeps_previous_manifest(self):
        self.insert(rec());d=self.agg();m.publish(self.db,d,self.site);old=(self.site/'data/physics.json').read_bytes();self.cat(d)['counts'][-1]+=1
        with self.assertRaises(m.HarvestError):m.publish(self.db,d,self.site)
        self.assertEqual((self.site/'data/physics.json').read_bytes(),old)
    def test_bootstrap_then_global_increment(self):
        c=Client([page([rec()],token='NEXT'),page([rec('2609.12346')])]);m.harvest(self.db,self.tax,ASOF,60,c)
        self.assertIn('set=physics',c.urls[0]);self.assertIn('resumptionToken=NEXT',c.urls[1]);self.assertNotIn('metadataPrefix',c.urls[1])
        c2=Client([page([rec(cats='cs.LG')])]);m.harvest(self.db,self.tax,ASOF,60,c2);self.assertNotIn('set=',c2.urls[0]);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0],1)
    def test_expand_verified_window(self):
        with self.db:m.put_meta(self.db,'coverage_from','2025-09-01T00:00:00Z');m.put_meta(self.db,'last_success',m.stamp(ASOF))
        c=Client([page([rec()])]);m.harvest(self.db,self.tax,ASOF,60,c);self.assertIn('from=2021-09-01',c.urls[0]);self.assertIn('set=physics',c.urls[0])
    def test_checkpoint_on_page_limit(self):
        with self.assertRaises(m.HarvestError):m.harvest(self.db,self.tax,ASOF,60,Client([page([rec()],token='NEXT')]),max_pages=1)
        self.assertEqual(m.get_meta(self.db,'checkpoint')['token'],'NEXT');self.assertIsNone(m.get_meta(self.db,'last_success'))
    def test_expired_token_restart_idempotent(self):
        with self.assertRaises(m.HarvestError):m.harvest(self.db,self.tax,ASOF,60,Client([page([rec()],token='EXPIRED')]),max_pages=1)
        c=Client([page([],error='badResumptionToken'),page([rec()])]);m.harvest(self.db,self.tax,ASOF,60,c)
        self.assertIn('resumptionToken=EXPIRED',c.urls[0]);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0],1)
    def test_full_sync_removes_stale_row_only_after_finish(self):
        self.insert(rec('2609.99999'))
        with self.assertRaises(m.HarvestError):m.harvest(self.db,self.tax,ASOF,60,Client([page([rec()],token='NEXT')]),max_pages=1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0],2)
        m.harvest(self.db,self.tax,ASOF,60,Client([page([])]));self.assertEqual(self.db.execute('SELECT id FROM papers').fetchone()[0],'2609.12345')
    def test_retention_advances(self):
        m.harvest(self.db,self.tax,ASOF,3,Client([page([rec()])]))
        m.harvest(self.db,self.tax,m.utc_datetime('2026-10-02T00:00:00Z'),3,Client([page([])]))
        self.assertEqual(m.get_meta(self.db,'coverage_from'),'2026-07-01T00:00:00Z')
    def test_local_only_discloses_short_history(self):
        with self.db:m.put_meta(self.db,'coverage_from','2025-09-01T00:00:00Z');m.put_meta(self.db,'snapshot_as_of',m.stamp(ASOF))
        _,months,cov=m.local_coverage(self.db,60);self.assertEqual(months,12);self.assertTrue(cov['localOnly'])
    def test_local_only_refuses_pending_checkpoint(self):
        with self.db:m.put_meta(self.db,'checkpoint',{'token':'NEXT'})
        with self.assertRaises(m.HarvestError):m.local_coverage(self.db,60)
    def test_local_only_refuses_no_coverage(self):
        with self.assertRaises(m.HarvestError):m.local_coverage(self.db,60)
    def test_concurrent_local_writers_blocked(self):
        path=self.root/'locked.sqlite'
        with m.collector_lock(path):
            with self.assertRaises(m.HarvestError):
                with m.collector_lock(path):pass
    def test_legacy_migration_preserves_source_and_minimizes_target(self):
        path=self.root/'legacy.sqlite';src=sqlite3.connect(path)
        src.executescript('CREATE TABLE papers(id TEXT PRIMARY KEY,published TEXT,primary_cat TEXT,title TEXT,authors TEXT,summary TEXT);CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);')
        src.executemany('INSERT INTO papers VALUES (?,?,?,?,?,?)',[('2609.12345','2026-09-03T12:00:00Z','cond-mat.dis-nn','Recent title','FORBIDDEN_AUTHOR','FORBIDDEN_ABSTRACT'),('2509.12345','2025-09-03T12:00:00Z','cond-mat.dis-nn','Old title','FORBIDDEN_AUTHOR','FORBIDDEN_ABSTRACT')])
        for k,v in [('coverage_from','2025-09-01T00:00:00Z'),('snapshot_as_of',m.stamp(ASOF)),('last_success',m.stamp(ASOF))]:src.execute('INSERT INTO meta VALUES (?,?)',(k,json.dumps(v)))
        src.commit();src.close();before=path.read_bytes()
        m.migrate_legacy(self.db,path,self.site,ASOF,60,2,True)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0],2);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM recent_titles').fetchone()[0],1)
        self.assertEqual(m.local_coverage(self.db,60)[1],12)
        dump=''.join(self.db.iterdump());self.assertNotIn('FORBIDDEN',dump);self.assertNotIn('Old title',dump)
        m.migrate_legacy(self.db,path,self.site,ASOF,60,2,True);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM papers').fetchone()[0],2)

if __name__=='__main__':unittest.main()
