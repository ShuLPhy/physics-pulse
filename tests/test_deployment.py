"""Offline-only deployment/retention tests. No GitHub writes or arXiv calls."""
from pathlib import Path
from datetime import timedelta
import gzip
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import update_data as m
import paper_metadata as md
import deploy_state as state
import github_state as remote
import cloud_build
import prepare_publish
import publish_github
import validate_site
from test_pipeline import ASOF,Client,page,rec


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'source.sqlite'
        self.db=m.connect_db(self.path);self.addCleanup(self.db.close)
        self.tax=json.loads((ROOT/'scripts/taxonomy.json').read_text())
        self.allowed={c['id'] for c in self.tax['categories']}
        with self.db:
            for pid,date in [('2109.10001','2021-09-10T00:00:00Z'),('2110.10001','2021-10-10T00:00:00Z'),('2111.10001','2021-11-10T00:00:00Z'),('2609.10001','2026-09-10T00:00:00Z')]:
                m.upsert_records(self.db,[{'id':pid,'created':m.epoch(m.utc_datetime(date)),'category':'cond-mat.dis-nn','title':'Fixture '+pid,'authors':'First Author; Second Author'}],m.retention_start(ASOF,60),self.allowed,m.retention_start(ASOF,60))
                self.db.execute('UPDATE paper_details SET abstract_gz=? WHERE id=?',(gzip.compress(b'Restored transport abstract'),pid))
            for key,value in [('coverage_from',m.stamp(m.retention_start(ASOF,60))),('snapshot_as_of',m.stamp(ASOF)),('last_success',m.stamp(ASOF))]:m.put_meta(self.db,key,value)
    def prune(self,dt=ASOF,full=False):return m.prune_monthly(self.db,dt,60,self.tax,full_window=full)
    def ids(self):return {r[0] for r in self.db.execute('SELECT id FROM papers')}
    def bundle(self,name='bundle'):return state.export_bundle(self.path,self.root/name)
    def build(self):
        return cloud_build.build(self.path,self.root/'site',self.root/'output')


class TestRotation(Fixture):
    def test_removes_baseline_papers_not_visible_month(self):
        report=self.prune();self.assertEqual(report['deletedPapers'],1)
        self.assertNotIn('2109.10001',self.ids());self.assertIn('2110.10001',self.ids())
    def test_cascades_bibliography_and_recent_titles(self):
        self.prune()
        for table in ('recent_titles','paper_details'):
            self.assertIsNone(self.db.execute(f'SELECT id FROM {table} WHERE id=?',('2109.10001',)).fetchone())
    def test_oldest_visible_comparison_still_available(self):
        self.prune();asof,n,cov=m.local_coverage(self.db,60)
        snap=m.aggregate(self.db,self.tax,asof,n,cov)
        cat=next(c for c in snap['categories'] if c['id']=='cond-mat.dis-nn')
        self.assertEqual(cat['baselinePreviousCount'],1);self.assertEqual(cat['counts'][0],1)
    def test_same_month_repeat_does_not_reset_baseline_to_zero(self):
        self.prune();report=self.prune();self.assertFalse(report['rotated'])
        self.assertEqual(self.db.execute('SELECT n FROM monthly_baseline WHERE category=?',('cond-mat.dis-nn',)).fetchone()[0],1)
    def test_next_month_rotates_exactly_one_month(self):
        self.prune();october=m.utc_datetime('2026-10-02T00:00:00Z')
        report=self.prune(october)
        self.assertTrue(report['rotated']);self.assertNotIn('2110.10001',self.ids());self.assertIn('2111.10001',self.ids())
        self.assertEqual({r[0] for r in self.db.execute('SELECT month FROM monthly_baseline')},{'2021-10'})
    def test_month_jump_drops_all_expired_records(self):
        self.prune();report=self.prune(m.utc_datetime('2026-12-02T00:00:00Z'))
        self.assertNotIn('2111.10001',self.ids());self.assertEqual(report['individualRecordsFrom'],'2022-01-01T00:00:00Z')
    def test_rotation_refuses_incomplete_state(self):
        with self.db:m.put_meta(self.db,'checkpoint',{'token':'unfinished'})
        before=self.ids()
        with self.assertRaises(m.HarvestError):self.prune()
        self.assertEqual(before,self.ids())
    def test_old_baseline_changes_not_false_recount(self):
        self.prune()
        with self.db:m.upsert_records(self.db,[{'id':'2109.99999','created':m.epoch(m.utc_datetime('2021-09-20T00:00:00Z')),'category':'cond-mat.dis-nn'}],m.retention_start(ASOF,60),self.allowed)
        self.prune();self.assertNotIn('2109.99999',self.ids())
        self.assertEqual(self.db.execute('SELECT n FROM monthly_baseline WHERE category=?',('cond-mat.dis-nn',)).fetchone()[0],1)
    def test_no_hidden_month_of_ids_remains(self):
        self.prune()
        self.assertGreaterEqual(self.db.execute('SELECT MIN(created) FROM papers').fetchone()[0],m.epoch(m.shift_month(ASOF,-59)))
    def test_baseline_full_resync_recomputes_counts(self):
        self.prune()
        with self.db:m.upsert_records(self.db,[{'id':'2109.99999','created':m.epoch(m.utc_datetime('2021-09-20T00:00:00Z')),'category':'cond-mat.dis-nn'}],m.retention_start(ASOF,60),self.allowed)
        self.prune(full=True)
        self.assertEqual(self.db.execute('SELECT n FROM monthly_baseline WHERE category=?',('cond-mat.dis-nn',)).fetchone()[0],1)
    def test_incremental_guard_stops_before_network(self):
        with self.db:self.db.execute("DELETE FROM meta WHERE key='last_success'")
        client=Client([])
        with self.assertRaisesRegex(m.HarvestError,'Full-window'):
            m.harvest(self.db,self.tax,ASOF,60,client,incremental_only=True)
        self.assertEqual(client.urls,[])
    def test_daily_query_is_incremental_and_keeps_authors(self):
        self.prune();client=Client([page([rec()])])
        cov=m.harvest(self.db,self.tax,ASOF,60,client,incremental_only=True)
        self.assertFalse(cov['fullWindow']);self.assertNotIn('set=physics',client.urls[0]);self.assertIn('from=2026-09-09',client.urls[0])
        self.assertIsNotNone(self.db.execute("SELECT authors FROM paper_details WHERE id='2609.12345'").fetchone()[0])
    def test_cloud_missing_db_no_file_or_request(self):
        p=self.root/'missing.sqlite'
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('network')) as call:
            with self.assertRaises(m.HarvestError):cloud_build.build(p,self.root/'site',self.root/'out',update=True)
            call.assert_not_called()
        self.assertFalse(p.exists())


class TestPortableState(Fixture):
    def test_export_input_unchanged(self):
        before=[tuple(r) for r in self.db.execute('SELECT * FROM papers ORDER BY id')]
        self.bundle();self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM papers ORDER BY id')])
        self.assertIsNone(m.get_meta(self.db,'baseline_month'))
    def test_round_trip_core_and_authors(self):
        manifest=self.bundle();target=self.root/'imported.sqlite';state.import_bundle(manifest,target)
        d=m.connect_db(target)
        try:
            self.assertEqual(d.execute('SELECT COUNT(*) FROM papers').fetchone()[0],3)
            self.assertIn('First Author',d.execute('SELECT authors FROM paper_details LIMIT 1').fetchone()[0])
            self.assertTrue(md.unpack_abstract(d.execute('SELECT abstract_gz FROM paper_details LIMIT 1').fetchone()[0]))
        finally:d.close()
    def test_private_meta_and_arbitrary_tables_excluded(self):
        with self.db:
            m.put_meta(self.db,'legacy_import',{'source':'/Users/PRIVATE_PATH/arxiv.sqlite'})
            m.put_meta(self.db,'unexpected_key','SECRET_TOKEN')
            self.db.execute('CREATE TABLE private_notes(secret TEXT)')
            self.db.execute("INSERT INTO private_notes VALUES ('SECRET_NOTE')")
        manifest=self.bundle();data=json.loads(manifest.read_text());raw=gzip.decompress(manifest.with_name(data['file']).read_bytes())
        for text in (b'PRIVATE_PATH',b'SECRET_TOKEN',b'SECRET_NOTE',b'private_notes'):self.assertNotIn(text,raw)
    def test_corrupt_blob_rejected_without_target(self):
        manifest=self.bundle();data=json.loads(manifest.read_text());blob=manifest.with_name(data['file']);blob.write_bytes(blob.read_bytes()+b'bad')
        target=self.root/'target.sqlite'
        with self.assertRaises(m.HarvestError):state.import_bundle(manifest,target)
        self.assertFalse(target.exists())
    def test_path_traversal_manifest_rejected(self):
        manifest=self.bundle();data=json.loads(manifest.read_text());data['file']='../escape.sqlite.gz';manifest.write_text(json.dumps(data))
        with self.assertRaises(m.HarvestError):state.import_bundle(manifest,self.root/'x.sqlite')
    def test_unfinished_seed_refused(self):
        with self.db:m.put_meta(self.db,'checkpoint',{'token':'unfinished'})
        with self.assertRaises(m.HarvestError):self.bundle()
    def test_too_short_seed_refused(self):
        with self.db:m.put_meta(self.db,'coverage_from','2025-09-01T00:00:00Z')
        with self.assertRaisesRegex(m.HarvestError,'12/60|Only'):
            self.bundle()
    def test_existing_target_not_overwritten(self):
        manifest=self.bundle();p=self.root/'existing.sqlite';p.write_bytes(b'preserve')
        with self.assertRaises(m.HarvestError):state.import_bundle(manifest,p)
        self.assertEqual(p.read_bytes(),b'preserve')
    def test_excessive_expanded_size_rejected(self):
        manifest=self.bundle();data=json.loads(manifest.read_text());data['sqliteBytes']=state.MAX_DB_BYTES+1;manifest.write_text(json.dumps(data))
        with self.assertRaises(m.HarvestError):state.import_bundle(manifest,self.root/'x.sqlite')
    def test_export_reads_committed_wal(self):
        self.assertEqual(self.db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
        manifest=self.bundle();self.assertEqual(json.loads(manifest.read_text())['papers'],3)
    def test_cannot_export_over_source(self):
        with self.assertRaises(m.HarvestError):state.sanitize_copy(self.path,self.path)
    def test_no_network_during_export(self):
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('network')) as call:self.bundle();call.assert_not_called()


class TestCloudBuild(Fixture):
    def test_first_publish_uses_no_arxiv_requests(self):
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('network')) as call:
            self.build();call.assert_not_called()
        report=validate_site.validate(self.root/'site',allow_stale=True)
        self.assertEqual(report['visibleMonths'],60);self.assertEqual(report['mode'],'live')
    def test_build_has_health_and_no_private_db(self):
        self.build();self.assertTrue((self.root/'site/health.json').is_file())
        self.assertFalse(list((self.root/'site').rglob('*.sqlite*')))
    def test_generated_refs_have_no_expired_month(self):
        self.build();snap=json.loads((self.root/'site/data/physics.json').read_text())
        self.assertNotIn('2021-09-01',snap['paperFiles']);self.assertIn('2021-10-01',snap['paperFiles'])
    def test_refuses_nonempty_staging_no_deletion(self):
        site=self.root/'site';site.mkdir();(site/'keep.txt').write_text('keep')
        with self.assertRaises(m.HarvestError):self.build()
        self.assertEqual((site/'keep.txt').read_text(),'keep')
    def test_failure_does_not_touch_previously_published_site(self):
        old=self.root/'old-site';old.mkdir();(old/'index.html').write_text('previous good site')
        with patch.object(m.SerialHTTP,'request',side_effect=m.HarvestError('fixture error')):
            with self.assertRaises(m.HarvestError):cloud_build.build(self.path,self.root/'site',self.root/'out',update=True)
        self.assertEqual((old/'index.html').read_text(),'previous good site')
        self.assertFalse((self.root/'site/index.html').exists())
    def test_rejects_orphaned_public_shards(self):
        self.build();path=self.root/'site/data/papers/old.json.gz';path.write_bytes(gzip.compress(b'{}'))
        with self.assertRaisesRegex(m.HarvestError,'orphaned'):validate_site.validate(self.root/'site',allow_stale=True)
    def test_rejects_demo_before_deploy(self):
        self.build();path=self.root/'site/data/physics.json';data=json.loads(path.read_text());data['mode']='demo';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(m.HarvestError,'DEMO|demo'):validate_site.validate(self.root/'site',allow_stale=True)
    def test_rejects_missing_shard(self):
        self.build();next((self.root/'site/data/papers').rglob('*.gz')).unlink()
        with self.assertRaises(m.HarvestError):validate_site.validate(self.root/'site',allow_stale=True)
    def test_rejects_private_files(self):
        self.build();(self.root/'site/.env').write_text('secret')
        with self.assertRaises(m.HarvestError):validate_site.validate(self.root/'site',allow_stale=True)
    def test_website_contains_searchable_saved_author_and_abstract(self):
        self.build();p=next((self.root/'site/data/papers/2026-09-01').glob('*.gz'))
        payload=json.loads(gzip.decompress(p.read_bytes()))
        self.assertIn('First Author',payload['papers'][0][3]);self.assertIn('transport',payload['papers'][0][4])


class FakeGitHub:
    def __init__(self):self.files={};self.calls=[];self.fail_manifest=False;self.corrupt_readback=False
    def __call__(self,*args,**kwargs):
        self.calls.append(args)
        if args[:2]==('release','view'):
            return json.dumps({'assets':[{'name':n,'size':len(b)} for n,b in self.files.items()]})
        if args[:2]==('release','upload'):
            p=Path(args[3])
            if self.fail_manifest and p.suffix=='.json':raise m.HarvestError('Upload failed')
            self.files[p.name]=p.read_bytes();return ''
        if args[:2]==('release','download'):
            name=args[args.index('--pattern')+1];out=Path(args[args.index('--dir')+1]);out.mkdir(parents=True,exist_ok=True)
            value=self.files[name]
            if self.corrupt_readback and name.endswith('.sqlite.gz'):value+=b'corrupt'
            (out/name).write_bytes(value);return ''
        if args[:2]==('release','delete-asset'):
            self.files.pop(args[3]);return ''
        raise AssertionError(args)


class TestRemoteLifecycle(Fixture):
    def test_round_trip_release_and_prune_previous_pair(self):
        fake=FakeGitHub();first=self.bundle('first');second=self.bundle('second')
        with patch.object(remote,'gh',side_effect=fake):
            remote.upload('user/repo',first);remote.upload('user/repo',second)
            self.assertEqual(set(fake.files),{second.name,second.stem+'.sqlite.gz'})
            result=remote.download('user/repo',self.root/'received',self.root/'new.sqlite')
            self.assertEqual(result['months'],60)
    def test_manifest_uploaded_last(self):
        fake=FakeGitHub();manifest=self.bundle()
        with patch.object(remote,'gh',side_effect=fake):remote.upload('user/repo',manifest)
        calls=[a for a in fake.calls if a[:2]==('release','upload')]
        self.assertTrue(calls[0][3].endswith('.sqlite.gz'));self.assertTrue(calls[1][3].endswith('.json'))
    def test_failed_commit_preserves_previous_state(self):
        fake=FakeGitHub();first=self.bundle('first');second=self.bundle('second')
        with patch.object(remote,'gh',side_effect=fake):
            remote.upload('user/repo',first);fake.fail_manifest=True
            with self.assertRaises(m.HarvestError):remote.upload('user/repo',second)
        self.assertIn(first.name,fake.files);self.assertIn(first.stem+'.sqlite.gz',fake.files)
    def test_corrupt_readback_does_not_delete_previous_pair(self):
        fake=FakeGitHub();first=self.bundle('first');second=self.bundle('second')
        with patch.object(remote,'gh',side_effect=fake):
            remote.upload('user/repo',first);fake.corrupt_readback=True
            with self.assertRaises(m.HarvestError):remote.upload('user/repo',second)
        self.assertIn(first.name,fake.files)
    def test_no_release_seed_does_not_harvest(self):
        fake=FakeGitHub()
        with patch.object(remote,'gh',side_effect=fake),patch.object(m.SerialHTTP,'request',side_effect=AssertionError('network')) as call:
            with self.assertRaises(m.HarvestError):remote.download('user/repo',self.root/'incoming',self.root/'new.sqlite')
            call.assert_not_called()
    def test_unrelated_release_asset_preserved(self):
        fake=FakeGitHub();fake.files['README.txt']=b'preserve';manifest=self.bundle()
        with patch.object(remote,'gh',side_effect=fake):remote.upload('user/repo',manifest)
        self.assertEqual(fake.files['README.txt'],b'preserve')
    def test_invalid_repository_rejected(self):
        for repo in ('https://github.com/x/y','../foo','x/y/z','x/--evil'):
            with self.assertRaises(m.HarvestError):remote.validate_repo(repo)


class TestHandoff(Fixture):
    def test_source_package_excludes_all_databases_and_generated_site(self):
        report=prepare_publish.prepare(self.path,self.root/'package')
        source=Path(report['source'])
        self.assertTrue((source/'.github/workflows/refresh.yml').is_file())
        self.assertTrue((source/'.github/publication.json').is_file())
        self.assertFalse((source/'.cache').exists());self.assertFalse((source/'site').exists());self.assertFalse(list(source.rglob('*.sqlite*')))
    def test_preparation_never_touches_arxiv(self):
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('network')) as call:
            prepare_publish.prepare(self.path,self.root/'package');call.assert_not_called()
    def test_publish_requires_explicit_public_flag_before_network(self):
        with patch.object(remote,'gh',side_effect=AssertionError('network')) as call:
            with self.assertRaises(m.HarvestError):publish_github.start('physics-pulse',self.path,False)
            call.assert_not_called()
    def test_publish_rejects_shell_injection_names(self):
        with self.assertRaises(m.HarvestError):publish_github.start('a;rm -rf x',self.path,True)
    def test_schedule_is_daily_and_no_cancel(self):
        text=(ROOT/'.github/workflows/refresh.yml').read_text()
        self.assertIn("cron: '17 6 * * *'",text);self.assertIn('cancel-in-progress: false',text);self.assertIn('retention-days: 1',text)
        self.assertIn('name: github-pages',text);self.assertNotIn('actions/cache',text)


class TestBootstrap(Fixture):
    def fake_root(self):
        root=self.root/'project';root.mkdir()
        for sub in ('scripts','tests','.github'):
            shutil.copytree(ROOT/sub,root/sub,ignore=shutil.ignore_patterns('__pycache__'))
        for name in prepare_publish.ROOT_FILES:shutil.copyfile(ROOT/name,root/name)
        return root
    def test_setup_resume_does_not_create_or_seed_twice(self):
        root=self.fake_root();fake=FakeGitHub();calls=[];flags={'release':False,'pages':False,'fail':True}
        def gh(*args,**kwargs):
            calls.append(args)
            if args[:2]==('api','user'):return json.dumps({'login':'fixture-user','id':123})
            if args[:2]==('repo','create'):return ''
            if args[:2]==('release','view') and not flags['release']:raise m.HarvestError('HTTP 404 release not found')
            if args[:2]==('release','create'):flags['release']=True;return ''
            if args[:2]==('api','repos/fixture-user/pulse/pages'):
                if not flags['pages']:raise m.HarvestError('HTTP 404 not found')
                return json.dumps({'build_type':'workflow'})
            if args[:3]==('api','--method','POST'):flags['pages']=True;return json.dumps({'build_type':'workflow'})
            if args[:2]==('workflow','run'):
                if flags['fail']:flags['fail']=False;raise m.HarvestError('Temporary dispatch failure')
                return ''
            return fake(*args,**kwargs)
        def git(directory,*args):
            if args[0]=='init':(directory/'.git').mkdir()
            return ''
        with patch.object(m,'ROOT',root),patch.object(remote,'gh',side_effect=gh),patch.object(publish_github,'git',side_effect=git),patch.object(shutil,'which',return_value='/usr/bin/mock'),patch.object(m.SerialHTTP,'request',side_effect=AssertionError('arxiv network')) as request:
            with self.assertRaises(m.HarvestError):publish_github.start('pulse',self.path,True)
            publish_github.start('pulse',self.path,True)
            request.assert_not_called()
        self.assertEqual(sum(a[:2]==('repo','create') for a in calls),1)
        self.assertEqual(sum(a[:2]==('release','upload') for a in calls),2)
        receipt=json.loads((root/'.publish/pulse/launch.json').read_text())
        self.assertTrue(receipt['dispatched'])
    def test_existing_remote_is_not_adopted(self):
        root=self.fake_root()
        def gh(*args,**kwargs):
            if args[:2]==('api','user'):return json.dumps({'login':'fixture-user','id':123})
            if args[:2]==('repo','create'):raise m.HarvestError('Repository already exists')
            raise AssertionError('Unexpected write after repository refusal: '+str(args))
        with patch.object(m,'ROOT',root),patch.object(remote,'gh',side_effect=gh),patch.object(shutil,'which',return_value='/usr/bin/mock'),patch.object(publish_github,'git',side_effect=AssertionError('git write')):
            with self.assertRaisesRegex(m.HarvestError,'already exists'):publish_github.start('pulse',self.path,True)

if __name__=='__main__':unittest.main()
