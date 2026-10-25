"""Remote project preparation and result packaging. No Unity activation on the host."""
import argparse,hashlib,json,os,re,shutil,tarfile
from pathlib import Path,PurePosixPath
from intake import fetch,extract,validate_manifest,digest,UNITY_VERSION,MAX_OUTPUT,safe_path

def plan(manifest,shards,license_workers):
 m=validate_manifest(json.loads(Path(manifest).read_text()))
 if not 1<=license_workers<=shards<=min(256,len(m['entries'])):raise ValueError('License worker count/shard count must be explicit and nonempty')
 return dict(shards=list(range(shards)),tracks=[t['id'] for t in m['tracks']],count=shards,licenseWorkers=license_workers)

def project_snapshot(output,sha):
 output=Path(output)
 if output.exists():raise ValueError('Project target must be new isolated workspace')
 archive=output.parent/'project-input.tar';fetch(os.environ['MYSIM_PROJECT_URL'],sha,archive,limit=6<<30)
 if shutil.disk_usage(output.parent).free<archive.stat().st_size*2+(4<<30):raise ValueError('Runner disk headroom insufficient for isolated Unity project')
 extract(archive,output,limit=10<<30);archive.unlink()
 if f'm_EditorVersion: {UNITY_VERSION}' not in (output/'ProjectSettings/ProjectVersion.txt').read_text():raise ValueError('Pinned Unity version mismatch')
 if (output/'Library').exists():raise ValueError('Snapshot must exclude machine-specific Library cache')
 editor=output/'Assets/MySimRemotePipeline/Editor';editor.mkdir(parents=True,exist_ok=True)
 shutil.copy2(Path(__file__).parents[1]/'Editor/RemoteCI.cs',editor/'RemoteCI.cs')

def verify_package(path,allowed_prefabs=()):
 # Unitypackages are tar.gz with hashed directory names and pathname records.
 with tarfile.open(path,'r:gz') as t:
  members=t.getmembers();paths={};seen=set();folders={'Assets','Assets/MySimRemoteGenerated','Assets/MySimRemoteGenerated/Meshes'}
  for asset in allowed_prefabs:folders.update(str(p) for p in PurePosixPath(asset).parents if str(p)!='.')
  if sum(m.size for m in members)>MAX_OUTPUT:raise ValueError('Unity package expanded budget exceeded')
  for m in members:
   safe_path('.',m.name)
   if m.name in seen:raise ValueError('Duplicate package member')
   seen.add(m.name)
   if not(m.isdir() or m.isfile()):raise ValueError('Package links not allowed')
   if m.name.endswith('/pathname'):
    name=t.extractfile(m).read().decode('utf-8').strip();safe_path('.',name)
    generated=bool(re.fullmatch(r'Assets/MySimRemoteGenerated/Meshes/[a-f0-9]{24}(?:/part-[0-9]{4}\.asset)?',name))
    if not(generated or name in folders or name in allowed_prefabs):raise ValueError('Unexpected package asset')
    if name.lower().endswith(('.cs','.dll','.so','.exe','.asmdef','.asmref')):raise ValueError('Executable code not allowed in generated asset package')
    paths[m.name.rsplit('/',1)[0]]=name
  for m in members:
   if m.isfile() and m.name.rsplit('/',1)[0] not in paths:raise ValueError('Unmapped package member')
 return paths

def seal(directory):
 directory=Path(directory)
 if not json.loads((directory/'report.json').read_text()).get('passed'):raise ValueError('No passed Unity report to seal')
 metrics=Path('/tmp/mysim-resource-watch.json')
 if os.name=='posix' and os.environ.get('GITHUB_ACTIONS')=='true' and metrics.exists():
  value=json.loads(metrics.read_text())
  if value.get('stop_reason'):raise ValueError('Remote resource watchdog stopped the worker')
  (directory/'resource-metrics.json').write_text(json.dumps(value))
 files={str(p.relative_to(directory)).replace('\\','/'):digest(p) for p in directory.rglob('*') if p.is_file() and p.name!='SHA256SUMS.json'}
 if sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())>MAX_OUTPUT:raise ValueError('1GiB output cutoff exceeded')
 (directory/'SHA256SUMS.json').write_text(json.dumps(files,indent=2));return files

def verify_results(root,manifest,stage):
 root=Path(root);seen=set();reports=[];track_ids=set();expected=validate_manifest(json.loads(Path(manifest).read_text()))
 for proof in root.rglob('SHA256SUMS.json'):
  hashes=json.loads(proof.read_text());actual={str(p.relative_to(proof.parent)).replace('\\','/') for p in proof.parent.rglob('*') if p.is_file() and p!=proof}
  if actual!=set(hashes) or 'report.json' not in hashes:raise ValueError('Unsealed or missing output file')
  for name,sha in hashes.items():
   p=safe_path(proof.parent,name)
   if digest(p)!=sha:raise ValueError('Changed worker output')
  report=json.loads((proof.parent/'report.json').read_text())
  if not report.get('passed') or report.get('stage')!=stage or report.get('unityVersion')!=UNITY_VERSION:raise ValueError('Unity worker did not pass correct stage/version')
  for ident in report.get('ids',[]):
   if ident in seen and stage=='validate':raise ValueError('Duplicate source in validation workers')
   seen.add(ident)
  for track in report.get('tracks',[]):
   if track in track_ids:raise ValueError('Duplicate assembled track')
   track_ids.add(track)
  allowed=[t['sourcePrefab'] for t in expected['tracks'] if t['id'] in report.get('tracks',[])] if stage in ('assemble','finish-track') else []
  packages=list(proof.parent.glob('*.unitypackage'))
  if not packages and stage!='export':raise ValueError('Passing report has no generated Unity package')
  if stage=='export' and any(not (proof.parent/'meshes'/ident/'mesh-index.json').exists() for ident in report['ids']):raise ValueError('Missing CPU exchange inventory')
  for package in packages:verify_package(package,allowed)
  reports.append(report)
 if not reports:raise ValueError('No verified Unity worker outputs')
 if seen!={e['id'] for e in expected['entries']}:raise ValueError('Missing or extraneous verified sources')
 if stage in ('assemble','finish-track') and track_ids!={t['id'] for t in expected['tracks']}:raise ValueError('Missing assembled tracks')
 return seen

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('plan');a.add_argument('--manifest',required=True);a.add_argument('--shards',type=int,required=True);a.add_argument('--license-workers',type=int,required=True)
 a=sub.add_parser('project');a.add_argument('--output',required=True);a.add_argument('--sha',required=True)
 a=sub.add_parser('seal');a.add_argument('--directory',required=True)
 a=sub.add_parser('verify');a.add_argument('--directory',required=True);a.add_argument('--manifest',required=True);a.add_argument('--stage',choices=['export','validate','assemble','finish-track'],required=True)
 args=p.parse_args()
 if args.command=='plan':print(json.dumps(plan(args.manifest,args.shards,args.license_workers)))
 elif args.command=='project':project_snapshot(args.output,args.sha)
 elif args.command=='seal':seal(args.directory)
 else:print('Verified unique source records:',len(verify_results(args.directory,args.manifest,args.stage)))
if __name__=='__main__':main()
