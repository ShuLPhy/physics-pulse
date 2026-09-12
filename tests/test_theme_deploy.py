from pathlib import Path
import gzip,json,sys,unittest,hashlib
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from test_deployment import Fixture
import update_data as m, themes, deploy_state, validate_site, upgrade_github

class ThemeCloud(Fixture):
    def test_old_state_additive_migration(self):
        self.db.execute('DROP TABLE theme_classifications');self.db.commit()
        manifest=self.bundle();p=self.root/'restore.sqlite';deploy_state.import_bundle(manifest,p)
        d=m.connect_db(p)
        try:self.assertEqual(d.execute('SELECT COUNT(*) FROM theme_classifications').fetchone()[0],0)
        finally:d.close()
    def test_state_roundtrip_preserves_discarded_abstract_tags(self):
        with self.db:themes.store(self.db,'2609.10001',themes.classify('Fixture 2609.10001','Anderson localization'),'observed')
        manifest=self.bundle();p=self.root/'restore.sqlite';deploy_state.import_bundle(manifest,p);d=m.connect_db(p)
        try:self.assertIn('anderson',json.loads(d.execute("SELECT hits FROM theme_classifications WHERE id='2609.10001' AND basis='title_abstract'").fetchone()[0]))
        finally:d.close()
    def test_cloud_build_no_network(self):
        with patch.object(m.SerialHTTP,'request',side_effect=AssertionError('network')) as call:self.build();call.assert_not_called()
        data=json.loads((self.root/'site/data/physics.json').read_text());self.assertEqual(data['themes']['ruleKey'],themes.rules()['ruleKey'])
        self.assertEqual(len(data['themes']['files']),60);validate_site.validate(self.root/'site',allow_stale=True)
    def test_tampered_theme_count_rejected(self):
        self.build();p=self.root/'site/data/physics.json';d=json.loads(p.read_text());d['themes']['basis']['title']['eligible'][-1]=999999;p.write_text(json.dumps(d))
        with self.assertRaises(m.HarvestError):validate_site.validate(self.root/'site',allow_stale=True)
    def test_tampered_sidecar_rejected(self):
        self.build();d=json.loads((self.root/'site/data/physics.json').read_text());p=self.root/'site'/d['themes']['files'][d['monthStarts'][-1]];p.write_bytes(gzip.compress(b'{}'))
        with self.assertRaises(m.HarvestError):validate_site.validate(self.root/'site',allow_stale=True)
    def test_monthly_rotation_removes_tags(self):
        with self.db:themes.store(self.db,'2110.10001',themes.classify('Anderson localization'))
        self.prune(m.utc_datetime('2026-10-02T00:00:00Z'))
        self.assertIsNone(self.db.execute("SELECT id FROM theme_classifications WHERE id='2110.10001'").fetchone())
    def test_expired_theme_shards_removed(self):
        self.build();p=self.root/'site/data/themes/2000-01-01-000000000000.json.gz';p.write_bytes(b'old')
        a,n,cov=m.local_coverage(self.db,60);snap=m.aggregate(self.db,self.tax,a,n,cov);m.publish(self.db,snap,self.root/'site');self.assertFalse(p.exists())
    def test_source_missing_is_not_download(self):
        with patch.object(m.SerialHTTP,'request') as request:
            with self.assertRaises(m.HarvestError):deploy_state.inspect_db(self.root/'missing.sqlite')
            request.assert_not_called()
    def test_upgrade_conflict_stops(self):
        s=self.root/'src';r=self.root/'repo';(s/'scripts').mkdir(parents=True);(r/'scripts').mkdir(parents=True)
        (s/'scripts/x.py').write_text('new');(r/'scripts/x.py').write_text('custom')
        manifest={'files':{'scripts/x.py':{'new':upgrade_github.sha(s/'scripts/x.py'),'old':[hashlib.sha256(b'old').hexdigest()]}}}
        with self.assertRaisesRegex(m.HarvestError,'custom changes'):upgrade_github.plan(s,r,manifest)
    def test_upgrade_exact_old_only(self):
        s=self.root/'src';r=self.root/'repo';(s/'scripts').mkdir(parents=True);(r/'scripts').mkdir(parents=True)
        (s/'scripts/x.py').write_text('new');(r/'scripts/x.py').write_text('old')
        manifest={'files':{'scripts/x.py':{'new':upgrade_github.sha(s/'scripts/x.py'),'old':[hashlib.sha256(b'old').hexdigest()]}}}
        self.assertEqual(upgrade_github.plan(s,r,manifest),['scripts/x.py'])
    def test_upgrade_traversal_rejected(self):
        with self.assertRaises(m.HarvestError):upgrade_github.plan(self.root,self.root,{'files':{'../bad':{'new':'x'}}})


class GitUpgrade(unittest.TestCase):
    def test_real_local_git_upgrade_and_idempotent_repeat(self):
        import tempfile,subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';(source/'scripts').mkdir(parents=True)
            original=root/'initial';original.mkdir();bare=root/'remote.git'
            def cmd(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
            cmd('git','init','-b','main',str(original));cmd('git','-C',str(original),'config','user.name','Fixture');cmd('git','-C',str(original),'config','user.email','fixture@example.invalid')
            (original/'VERSION').write_text('0.5.0\n');cmd('git','-C',str(original),'add','VERSION');cmd('git','-C',str(original),'commit','-m','old')
            cmd('git','clone','--bare',str(original),str(bare))
            (source/'VERSION').write_text('0.6.0\n')
            manifest={'files':{'VERSION':{'old':[upgrade_github.sha(original/'VERSION')],'new':upgrade_github.sha(source/'VERSION')}}}
            (source/'scripts/release_manifest.json').write_text(json.dumps(manifest))
            calls=[]
            def gh(*args):
                calls.append(args)
                if args[:2]==('repo','view'):return json.dumps({'nameWithOwner':'fixture/pulse','defaultBranchRef':{'name':'main'}})
                if args[:2]==('repo','clone'):return cmd('git','clone',str(bare),args[3])
                if args[:2]==('api','user'):return json.dumps({'login':'fixture','id':1})
                if args[:2]==('workflow','run'):return ''
                raise AssertionError('Unexpected external command: '+str(args))
            with patch.object(m,'ROOT',source),patch.object(upgrade_github.github_state,'gh',side_effect=gh),patch.object(upgrade_github.shutil,'which',return_value='/fixture'):
                upgrade_github.run('fixture/pulse',True)
                self.assertEqual(cmd('git','--git-dir',str(bare),'show','main:VERSION'),'0.5.0\n')
                self.assertFalse(any(c[:2]==('workflow','run') for c in calls))
                upgrade_github.run('fixture/pulse')
                self.assertEqual(cmd('git','--git-dir',str(bare),'show','main:VERSION'),'0.6.0\n')
                revision=cmd('git','--git-dir',str(bare),'rev-parse','main');upgrade_github.run('fixture/pulse');self.assertEqual(cmd('git','--git-dir',str(bare),'rev-parse','main'),revision)
            dispatch=[c for c in calls if c[:2]==('workflow','run')];self.assertTrue(dispatch);self.assertTrue(all('mode=publish-only' in c for c in dispatch))
            self.assertFalse(any(c[:2]==('release','upload') for c in calls))
    def test_path_parent_symlink_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp);src=r/'source';remote=r/'remote';outside=r/'outside';src.mkdir();remote.mkdir();outside.mkdir();(src/'scripts').mkdir();(src/'scripts/x.py').write_text('x');(remote/'scripts').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(m.HarvestError):upgrade_github.plan(src,remote,{'files':{'scripts/x.py':{'new':upgrade_github.sha(src/'scripts/x.py'),'old':[]}}})
    def test_resolve_receipt_without_guessing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.publish/physics-pulse';folder.mkdir(parents=True);(folder/'launch.json').write_text(json.dumps({'repo':'fixture/pulse','created':True}))
            with patch.object(m,'ROOT',root):self.assertEqual(upgrade_github.resolve_repo(),'fixture/pulse')
    def test_ambiguous_receipts_need_explicit_repo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n in ('one','two'):
                folder=root/'.publish'/n;folder.mkdir(parents=True);(folder/'launch.json').write_text(json.dumps({'repo':'fixture/'+n,'created':True}))
            with patch.object(m,'ROOT',root):
                with self.assertRaises(m.HarvestError):upgrade_github.resolve_repo()

if __name__=='__main__':unittest.main()
