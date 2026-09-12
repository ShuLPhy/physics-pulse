"""No network: lexical boundaries, missingness, versioning, joins and retention."""
import gzip,json,sys,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import themes as t
import update_data as m
import oai
from test_pipeline import ASOF,rec,page

class Rules(unittest.TestCase):
    def test_multilabel(self):
        h=t.classify('Superconductivity in a twisted bilayer using tensor networks')['title']['hits']
        self.assertTrue({'superconductivity','moire','tensor-networks'}<=set(h))
    def test_no_false_acronyms(self):
        self.assertFalse(t.classify('ML DFT QHE spin charge arbitrary')['title']['hits'])
    def test_word_boundary(self):
        self.assertFalse(t.classify('Microfloquetization and Montecarloff')['title']['hits'])
    def test_unicode_and_hyphen(self):
        h=t.classify('Moir\u00e9 and many\u2011body localisation')['title']['hits'];self.assertIn('moire',h);self.assertIn('many-body-localization',h)
    def test_case(self):self.assertIn('quantum-hall',t.classify('QUANTUM HALL EFFECT')['title']['hits'])
    def test_no_input_is_not_no_hit(self):self.assertEqual(t.classify(None,'Quantum Hall'),{})
    def test_unmatched_is_evaluated(self):self.assertEqual(t.classify('Ordinary material study')['title']['hits'],{})
    def test_no_abstract_no_enriched(self):self.assertNotIn('title_abstract',t.classify('Superconductivity'))
    def test_cohorts_do_not_mix(self):
        h=t.classify('A tunable material','Quantum Hall effect');self.assertNotIn('quantum-hall',h['title']['hits']);self.assertIn('quantum-hall',h['title_abstract']['hits'])
    def test_evidence_field(self):
        e=t.classify('A material','Quantum Hall effect')['title_abstract']['hits']['quantum-hall'];self.assertEqual(e,[{'field':'abstract','phrase':'quantum Hall'}])
    def test_parent_union(self):
        h=t.classify('Anderson localization and many body localization')['title']['hits'];self.assertEqual(sum(x=='localization' for x in h),1)
    def test_neural_network_not_always_method(self):self.assertNotIn('learning-methods',t.classify('Dynamics of a neural network')['title']['hits'])
    def test_source_body_not_in_tags(self):
        h=t.classify('Quantum Hall','SECRETUNIQUE: Quantum Hall effect in a new system');self.assertNotIn('SECRETUNIQUE',json.dumps(h))
    def test_rule_key_frozen(self):self.assertTrue(t.rules()['ruleKey'].startswith('cm-1.0.0+'));self.assertEqual(len(t.rules()['fingerprint']),16)

class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.db=m.connect_db(self.root/'db.sqlite');self.addCleanup(self.db.close)
        self.tax=json.loads((ROOT/'scripts/taxonomy.json').read_text());self.allowed={c['id'] for c in self.tax['categories']}
    def insert(self,id='2609.12345',title='Quantum Hall effect',abstract=None,category='cond-mat.mes-hall',date='2026-09-03T12:00:00Z'):
        p={'id':id,'created':m.epoch(m.utc_datetime(date)),'category':category,'title':title,'authors':'A. Example'}
        if abstract is not None:p['_themes']=t.classify(title,abstract)
        with self.db:m.upsert_records(self.db,[p],m.retention_start(ASOF,60),self.allowed,m.retention_start(ASOF,60))
    def test_cascade_deletion(self):
        self.insert();self.db.execute('DELETE FROM papers');self.assertEqual(self.db.execute('SELECT COUNT(*) FROM theme_classifications').fetchone()[0],0)
    def test_reclassification_outside_condmat(self):
        self.insert();self.insert(category='quant-ph');self.assertEqual(self.db.execute('SELECT COUNT(*) FROM theme_classifications').fetchone()[0],0)
    def test_idempotent_observe(self):
        self.insert(abstract='Quantum Hall');self.insert(abstract='Quantum Hall');self.assertEqual(self.db.execute('SELECT COUNT(*) FROM theme_classifications').fetchone()[0],2)
    def test_changed_title_invalidates_abstract_tag(self):
        self.insert(abstract='Anderson localization');self.insert(title='New title');self.assertEqual(self.db.execute("SELECT COUNT(*) FROM theme_classifications WHERE basis='title_abstract'").fetchone()[0],0)
    def test_observed_tags_not_replaced_by_old_abstract(self):
        self.insert(abstract='Anderson localization')
        self.db.execute("UPDATE paper_details SET abstract_gz=?",(gzip.compress(b'Tensor network method'),))
        t.backfill(self.db)
        h=json.loads(self.db.execute("SELECT hits FROM theme_classifications WHERE basis='title_abstract'").fetchone()[0]);self.assertIn('anderson',h);self.assertNotIn('tensor-networks',h)
    def test_backfill_restored_abstract(self):
        self.insert();self.db.execute('UPDATE paper_details SET abstract_gz=?',(gzip.compress(b'Anderson localization'),));self.db.commit();t.backfill(self.db)
        h=json.loads(self.db.execute("SELECT hits FROM theme_classifications WHERE basis='title_abstract'").fetchone()[0]);self.assertIn('anderson',h)
    def test_backfill_twice_no_changes(self):
        self.insert();t.backfill(self.db);before=self.db.total_changes;t.backfill(self.db);self.assertEqual(before,self.db.total_changes)
    def test_new_version_drops_unrebuildable_old_tags(self):
        self.insert(abstract='Anderson localization');self.db.execute("UPDATE theme_classifications SET rule_key='OLD'");self.db.commit();t.backfill(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM theme_classifications').fetchone()[0],1)
    def test_observed_empty_abstract_does_not_revive_old_abstract_tags(self):
        self.insert(abstract='Anderson localization')
        self.db.execute('UPDATE paper_details SET abstract_gz=?',(gzip.compress(b'Old Anderson localization'),))
        self.db.commit();self.insert(abstract='');t.backfill(self.db)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM theme_classifications WHERE basis='title_abstract'").fetchone()[0],0)
    def test_counts_and_sync_not_changed(self):
        self.insert();m.put_meta(self.db,'last_success','fixed');self.db.commit();before=[tuple(r) for r in self.db.execute('SELECT * FROM papers')];t.backfill(self.db)
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM papers')]);self.assertEqual(m.get_meta(self.db,'last_success'),'fixed')
    def test_summary_denominator_and_unmatched(self):
        self.insert();self.insert(id='2609.12346',title='Other material')
        self.insert(id='2609.12347',title=None)
        cov={'complete':True,'from':m.stamp(m.retention_start(ASOF,60)),'to':m.stamp(ASOF)}
        snap=m.aggregate(self.db,self.tax,ASOF,60,cov);x=t.summary(self.db,snap)
        self.assertEqual(x['totals'][-1],3);self.assertEqual(x['basis']['title']['eligible'][-1],2);self.assertEqual(x['basis']['title']['unmatched'][-1],1)
    def test_future_submissions_excluded(self):
        self.insert(date='2026-09-30T00:00:00Z');snap=m.aggregate(self.db,self.tax,ASOF,60,{'complete':True,'from':m.stamp(m.retention_start(ASOF,60)),'to':m.stamp(ASOF)})
        self.assertEqual(t.summary(self.db,snap)['basis']['title']['eligible'][-1],0)
    def test_month_sidecar_no_abstract_or_title(self):
        self.insert(abstract='Quantum Hall');raw=json.dumps(t.month_index(self.db,'2026-09-01',ASOF));self.assertNotIn('A. Example',raw);self.assertNotIn('abstract_gz',raw)
    def test_parse_analyze_before_discard(self):
        xml=page([rec(title='Study of matter')]).replace(b'ABSTRACT_MUST_NOT_BE_RETAINED',b'Anderson localization SECRET_BODY')
        # Test fixture uses a long distinctive abstract; replace its element text directly.
        import xml.etree.ElementTree as ET
        root=ET.fromstring(xml)
        for el in root.iter():
            if oai.local_name(el)=='abstract':el.text='Anderson localization SECRET_BODY'
        out=oai.parse_oai(ET.tostring(root),m.retention_start(ASOF,60),author_minimum=m.retention_start(ASOF,60),theme_minimum=m.retention_start(ASOF,60))
        p=out['records'][0];self.assertIn('anderson',p['_themes']['title_abstract']['hits']);self.assertNotIn('SECRET_BODY',json.dumps(p));self.assertNotIn('abstract',p)
    def test_no_abstract_newly_persisted(self):
        self.insert(abstract='Anderson localization SECRET');self.assertIsNone(self.db.execute('SELECT abstract_gz FROM paper_details').fetchone()[0])

if __name__=='__main__':unittest.main()
