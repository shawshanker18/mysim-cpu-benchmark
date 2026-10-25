"""Execute a frozen single-node input contract; node submission remains centrally budgeted."""
import argparse,json,os,re,shutil
from pathlib import Path
from intake import validate_manifest,digest,fetch,extract
from ci import project_snapshot,verify_results
def prepare(spec_path,sha,project,workspace):
 if digest(spec_path)!=sha:raise ValueError('Immutable node specification mismatch')
 spec=json.loads(Path(spec_path).read_text());stage=spec['stage'];m=validate_manifest(spec['manifest']);root=Path(workspace);root.mkdir(parents=True,exist_ok=True)
 if stage not in ('export','validate','finish-track','build'):raise ValueError('Unsupported node stage')
 if not re.fullmatch('[a-zA-Z0-9_-]{1,80}',spec['id']):raise ValueError('Invalid immutable node ID')
 if stage=='finish-track' and (len(m['tracks'])!=1 or spec.get('track')!=m['tracks'][0]['id']):raise ValueError('Track-local node required')
 (root/'manifest.json').write_text(json.dumps(m))
 if stage=='export':
  from intake import prepare as intake
  intake(root/'manifest.json',None,root/'intake',0,1,stage)
 else:
  project_snapshot(project,spec['projectSha256'])
  for i,item in enumerate(spec['packageInputs']):
   if item['stage'] not in ('export','validate','finish-track'):raise ValueError('Unknown dependency receipt phase')
   path=root/'downloads'/(item['sha256']+'.zip');fetch(item['url'],item['sha256'],path)
   extract(path,root/'packages'/item['stage']/str(i),limit=1<<30)
  if stage=='validate':
   verify_results(root/'packages/export',root/'manifest.json','export');destination=root/'intake';destination.mkdir(exist_ok=True);(destination/'shard.json').write_text(json.dumps(m))
   for folder in (root/'packages/export').glob('*/meshes/*'):
    if (destination/'meshes'/folder.name).exists():raise ValueError('Duplicate exchange source')
    shutil.copytree(folder,destination/'meshes'/folder.name)
  else:
   verify_results(root/'packages/validate',root/'manifest.json','validate')
   if stage=='build':verify_results(root/'packages/finish-track',root/'manifest.json','finish-track')
 return spec

def package_export(workspace,output):
 root=Path(workspace);out=Path(output);out.mkdir(parents=True,exist_ok=True);m=json.loads((root/'intake/shard.json').read_text())
 for e in m['entries']:
  source=root/'intake/meshes'/e['id'];target=out/'meshes'/e['id'];target.mkdir(parents=True,exist_ok=True)
  index=json.loads((source/'mesh-index.json').read_text())
  for part in index['parts']+index['collision']:
   if digest(source/part['file'])!=part['sha256']:raise ValueError('Exchange data changed')
   shutil.copy2(source/part['file'],target/part['file'])
  shutil.copy2(source/'mesh-index.json',target/'mesh-index.json')
 (out/'report.json').write_text(json.dumps(dict(passed=True,stage='export',unityVersion=m['unityVersion'],ids=[e['id'] for e in m['entries']],sourceUnityBindingVerified=False,finalArtisticUnityAccepted=False)))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--spec');p.add_argument('--sha');p.add_argument('--project',default='project');p.add_argument('--workspace',default='node-input');p.add_argument('--package-export');a=p.parse_args()
 if a.package_export:package_export(a.workspace,a.package_export);raise SystemExit(0)
 if not a.spec or not a.sha:raise ValueError('Frozen node specification/hash required')
 s=prepare(a.spec,a.sha,a.project,a.workspace)
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('stage='+s['stage']+'\ntrack='+s.get('track','')+'\n')
