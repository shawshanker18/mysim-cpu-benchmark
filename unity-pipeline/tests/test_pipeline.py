import copy,hashlib,io,json,math,struct,sys,tarfile,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
from intake import validate_manifest,extract,safe_path,UNITY_VERSION
from mesh_binary import write_mesh,read_mesh
from ci import seal,verify_results,verify_package,plan
from make_manifest import merge

def manifest():
 return dict(schema=1,unityVersion=UNITY_VERSION,tracks=[dict(id='track26',sourcePrefab='Assets/Resources/RealRacing/Track26.prefab',sourcePrefabSha256='c'*64)],entries=[dict(id='a'*24,sourceAsset='Assets/source.fbx',sourceSha256='1'*64,sourceMesh='drain',sourceFileId='4300000',sourceToUnity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],trackIds=['track26'],materialPaths=['Assets/source.mat'],lodHeights=[.5],parts=[dict(object='drain',lod=0)],collisionObject='drain__original_collision',blendMember='candidate.blend',reportMember='checkpoint.json',archiveSha256='2'*64,blendSha256='3'*64,archiveUrl='https://example.invalid/immutable.zip')],buildScenes=['Assets/Launch.unity'])

class PipelineTests(unittest.TestCase):
 def package(self,path):
  with tarfile.open(path,'w:gz') as t:
   for name,data in [('123/pathname',b'Assets/MySimRemoteGenerated/Meshes/'+b'a'*24+b'/part-0000.asset'),('123/asset',b'%YAML test asset payload'),('123/asset.meta',b'fileFormatVersion: 2')]:
    item=tarfile.TarInfo(name);item.size=len(data);t.addfile(item,io.BytesIO(data))
 def test_encoded_uv1_float32_roundtrip_is_exact(self):
  with tempfile.TemporaryDirectory() as d:
   # UV1.y includes page37; values outside0..1 must never be normalized.
   vertices=[(0,0,0,0,1,0,.5,.7,.2,37.8125),(1,0,0,0,1,0,1.5,-.7,.4,38.0),(0,0,1,0,1,0,.1,.3,.7,37.0625)]
   p=Path(d)/'mesh.bin';write_mesh(p,vertices,[[0,1,2]],2);r=read_mesh(p)
   for a,b in zip(vertices,r['vertices']):self.assertEqual(tuple(struct.unpack('<10f',struct.pack('<10f',*a))),b)
 def test_invalid_indices_and_nonfinite_data_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'mesh.bin'
   with self.assertRaises(ValueError):write_mesh(p,[(0,0,0,0,1,0)],[[0,1,0]],0)
   with self.assertRaises(ValueError):write_mesh(p,[(math.nan,0,0,0,1,0)],[[0,0,0]],0)
 def test_source_transform_must_be_explicit_and_nonsingular(self):
  m=manifest();self.assertIs(validate_manifest(m),m)
  for value in (None,[0]*16,[1]*16):
   bad=copy.deepcopy(m);bad['entries'][0]['sourceToUnity']=value
   with self.assertRaises((ValueError,TypeError)):validate_manifest(bad)
 def test_duplicate_source_or_track_ownership_rejected(self):
  m=manifest();m['entries']*=2
  with self.assertRaises(ValueError):validate_manifest(m)
  m=manifest();m['tracks'].append(dict(m['tracks'][0],id='other'))
  with self.assertRaises(ValueError):validate_manifest(m)
 def test_arbitrary_source_uv_lod_loss_not_accepted(self):
  m=manifest();m['entries'][0]['parts'].append(dict(object='lod2',lod=2))
  with self.assertRaises(ValueError):validate_manifest(m)
 def test_zip_traversal_rejected_before_writing(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'bad.zip'
   with zipfile.ZipFile(p,'w') as z:z.writestr('../outside','bad')
   with self.assertRaises(ValueError):extract(p,Path(d)/'safe')
   self.assertFalse((Path(d)/'outside').exists())
 def test_tar_link_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'bad.tar'
   with tarfile.open(p,'w') as t:
    item=tarfile.TarInfo('link');item.type=tarfile.SYMTYPE;item.linkname='/outside';t.addfile(item)
   with self.assertRaises(ValueError):extract(p,Path(d)/'safe')
 def test_missing_shard_or_tampered_result_stops_assembly(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);mp=root/'manifest.json';mp.write_text(json.dumps(manifest()));out=root/'outputs';out.mkdir();self.package(out/'meshes.unitypackage');(out/'report.json').write_text(json.dumps(dict(passed=True,stage='validate',unityVersion=UNITY_VERSION,ids=[])));seal(out)
   with self.assertRaises(ValueError):verify_results(out,mp,'validate')
   (out/'meshes.unitypackage').unlink();report=dict(passed=True,stage='validate',unityVersion=UNITY_VERSION,ids=['a'*24]);(out/'report.json').write_text(json.dumps(report));seal(out)
   with self.assertRaises(ValueError):verify_results(out,mp,'validate')
 def test_verified_package_inventory_passes_and_changed_payload_fails(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);mp=root/'manifest.json';mp.write_text(json.dumps(manifest()));out=root/'outputs';out.mkdir();self.package(out/'meshes.unitypackage')
   (out/'report.json').write_text(json.dumps(dict(passed=True,stage='validate',unityVersion=UNITY_VERSION,ids=['a'*24])));seal(out)
   self.assertEqual(verify_results(out,mp,'validate'),{'a'*24})
   with (out/'meshes.unitypackage').open('ab') as f:f.write(b'changed')
   with self.assertRaises(ValueError):verify_results(out,mp,'validate')
 def test_duplicate_verified_sources_do_not_pad_coverage(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);mp=root/'manifest.json';mp.write_text(json.dumps(manifest()))
   for number in range(2):
    out=root/'outputs'/str(number);out.mkdir(parents=True);self.package(out/'meshes.unitypackage');(out/'report.json').write_text(json.dumps(dict(passed=True,stage='validate',unityVersion=UNITY_VERSION,ids=['a'*24])));seal(out)
   with self.assertRaises(ValueError):verify_results(root/'outputs',mp,'validate')
 def test_licensing_count_is_independent_from_github_slots(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'manifest.json';p.write_text(json.dumps(manifest()));self.assertEqual(plan(p,1,1)['licenseWorkers'],1)
   with self.assertRaises(ValueError):plan(p,1,140)
 def test_no_empty_padding_shards(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'manifest.json';p.write_text(json.dumps(manifest()))
   with self.assertRaises(ValueError):plan(p,2,1)
 def test_package_cannot_inject_code_or_unlisted_source_prefab(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'bad.unitypackage'
   with tarfile.open(p,'w:gz') as t:
    data=b'Assets/Editor/Injected.cs';item=tarfile.TarInfo('123/pathname');item.size=len(data);t.addfile(item,io.BytesIO(data))
   with self.assertRaises(ValueError):verify_package(p)
 def test_final_manifest_does_not_allow_candidate_override(self):
  m=manifest();binding=copy.deepcopy(m['entries'][0]);archive={k:binding.pop(k) for k in ('archiveUrl','archiveSha256','blendMember','blendSha256','reportMember')};archive['id']=binding['id'];bindings=dict(entries=[binding],tracks=m['tracks'])
  self.assertEqual(len(merge(bindings,[archive],1)['entries']),1)
  archive['sourceAsset']='Assets/wrong.fbx'
  with self.assertRaises(ValueError):merge(bindings,[archive],1)
if __name__=='__main__':unittest.main()
