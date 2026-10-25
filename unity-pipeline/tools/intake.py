"""Hash-verified remote Unity intake. Never executes Unity or modifies the source project."""
import argparse,hashlib,json,math,os,re,shutil,stat,tarfile,urllib.parse,urllib.request,zipfile
from pathlib import Path,PurePosixPath

UNITY_VERSION='6000.3.26f1'
MAX_OUTPUT=1<<30

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(4<<20),b''):h.update(block)
 return h.hexdigest()

def safe_path(root,name):
 p=PurePosixPath(name)
 if not name or '\\' in name or ':' in name or p.is_absolute() or any(x in ('..','') for x in p.parts):raise ValueError('Unsafe archive/path member')
 target=(Path(root)/str(p)).resolve()
 if not target.is_relative_to(Path(root).resolve()):raise ValueError('Path escapes root')
 return target

def fetch(url,sha,target,limit=MAX_OUTPUT):
 if urllib.parse.urlsplit(url).scheme!='https':raise ValueError('HTTPS input required')
 if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('SHA256 required')
 target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists() and digest(target)==sha:return target
 temp=target.with_suffix(target.suffix+'.part');h=hashlib.sha256();size=0
 try:
  with urllib.request.urlopen(url,timeout=90) as src,temp.open('wb') as dst:
   if urllib.parse.urlsplit(src.url).scheme!='https':raise ValueError('Insecure redirect')
   for block in iter(lambda:src.read(4<<20),b''):
    size+=len(block)
    if size>limit:raise ValueError('Input size budget exceeded')
    h.update(block);dst.write(block)
  if h.hexdigest()!=sha:raise ValueError('Input SHA256 mismatch')
  temp.replace(target);return target
 finally:
  if temp.exists():temp.unlink()

def extract(archive,root,limit=10<<30):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);total=0
 if zipfile.is_zipfile(archive):
  with zipfile.ZipFile(archive) as z:
   seen=set()
   for item in z.infolist():
    target=safe_path(root,item.filename)
    if item.filename in seen:raise ValueError('Duplicate archive member')
    seen.add(item.filename);total+=item.file_size
    if total>limit or stat.S_ISLNK(item.external_attr>>16):raise ValueError('Unsafe or oversized archive')
   for item in z.infolist():
    target=safe_path(root,item.filename)
    if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
    target.parent.mkdir(parents=True,exist_ok=True)
    with z.open(item) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)
 else:
  with tarfile.open(archive,'r:*') as t:
   seen=set()
   for item in t:
    target=safe_path(root,item.name)
    if item.name in seen:raise ValueError('Duplicate archive member')
    seen.add(item.name);total+=item.size
    if total>limit or not(item.isfile() or item.isdir()):raise ValueError('Unsafe or oversized tar')
    if item.isdir():target.mkdir(parents=True,exist_ok=True);continue
    target.parent.mkdir(parents=True,exist_ok=True)
    with t.extractfile(item) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)

def validate_manifest(m):
 if m.get('schema')!=1 or m.get('unityVersion')!=UNITY_VERSION:raise ValueError('Wrong schema or Unity version')
 if not m.get('entries') or not m.get('tracks'):raise ValueError('Nonempty mesh/track inventory required')
 ids=set();tracks={};sourcekeys=set()
 for track in m['tracks']:
  if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',track['id']) or track['id'] in tracks:raise ValueError('Duplicate/invalid track ID')
  if not track['sourcePrefab'].startswith('Assets/') or not track['sourcePrefab'].endswith('.prefab'):raise ValueError('Source prefab required')
  safe_path('.',track['sourcePrefab']);tracks[track['id']]=track
  if not re.fullmatch('[a-f0-9]{64}',track.get('sourcePrefabSha256','')):raise ValueError('Source prefab SHA256 required')
 if len({t['sourcePrefab'] for t in tracks.values()})!=len(tracks):raise ValueError('Two jobs may not own the same prefab')
 for e in m['entries']:
  if not re.fullmatch('[a-f0-9]{24}',e['id']) or e['id'] in ids:raise ValueError('Duplicate/invalid source ID')
  ids.add(e['id']);key=(e['sourceAsset'],e['sourceMesh'],e.get('sourceFileId',''))
  if key in sourcekeys:raise ValueError('Duplicate Unity source mesh binding')
  sourcekeys.add(key)
  if not e['sourceAsset'].startswith('Assets/'):raise ValueError('Project-relative source asset required')
  safe_path('.',e['sourceAsset'])
  if not re.fullmatch('[a-f0-9]{64}',e['sourceSha256']):raise ValueError('Source SHA256 required')
  matrix=e['sourceToUnity']
  if len(matrix)!=16 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in matrix):raise ValueError('Explicit finite source-to-Unity matrix required')
  if any(abs(matrix[i]-v)>1e-7 for i,v in zip((12,13,14,15),(0,0,0,1))):raise ValueError('Affine row-major matrix required')
  det=matrix[0]*(matrix[5]*matrix[10]-matrix[6]*matrix[9])-matrix[1]*(matrix[4]*matrix[10]-matrix[6]*matrix[8])+matrix[2]*(matrix[4]*matrix[9]-matrix[5]*matrix[8])
  if abs(det)<1e-15:raise ValueError('Singular source-to-Unity matrix')
  if not e.get('trackIds') or any(t not in tracks for t in e['trackIds']):raise ValueError('Missing track ownership')
  if not e.get('materialPaths') or any(not p.startswith('Assets/') for p in e['materialPaths']):raise ValueError('Exact Unity material paths required')
  for p in e['materialPaths']:safe_path('.',p)
  levels=sorted({p['lod'] for p in e['parts']})
  if levels!=list(range(len(levels))) or not levels:raise ValueError('LOD0 and continuous LOD levels required')
  heights=e['lodHeights']
  if len(heights)!=len(levels) or not all(0<x<1 for x in heights) or any(a<=b for a,b in zip(heights,heights[1:])):raise ValueError('Explicit descending LOD thresholds required')
  if not e.get('collisionObject') or len({p['object'] for p in e['parts']})!=len(e['parts']):raise ValueError('Unique part roles and original collision required')
  for k in ('blendMember','reportMember'):safe_path('.',e[k])
  for k in ('archiveSha256','blendSha256'):
   if not re.fullmatch('[a-f0-9]{64}',e[k]):raise ValueError('Archive and blend hashes required')
  if urllib.parse.urlsplit(e['archiveUrl']).scheme!='https':raise ValueError('HTTPS archive required')
 return m

def prepare(manifest,project,workspace,shard,shards,stage):
 m=validate_manifest(json.loads(Path(manifest).read_text()));w=Path(workspace);w.mkdir(parents=True,exist_ok=True)
 selected=sorted(m['entries'],key=lambda e:e['id'])[shard::shards]
 if not selected:raise ValueError('Empty shard, not padding work')
 version=(Path(project)/'ProjectSettings/ProjectVersion.txt').read_text()
 if f'm_EditorVersion: {UNITY_VERSION}' not in version:raise ValueError('Project version differs from pinned version')
 archive_cache={}
 for e in selected:
  source=safe_path(project,e['sourceAsset'])
  if not source.is_file() or digest(source)!=e['sourceSha256']:raise ValueError('Unity source asset SHA mismatch: '+e['id'])
  directory=w/'meshes'/e['id'];directory.mkdir(parents=True,exist_ok=True)
  sha=e['archiveSha256'];archive=w/'downloads'/(sha+'.zip')
  if sha not in archive_cache:
   fetch(e['archiveUrl'],sha,archive);archive_cache[sha]=archive
  with zipfile.ZipFile(archive) as z:
   entries=json.loads(z.read('SHA256SUMS.json'))
   if entries.get(e['blendMember'])!=e['blendSha256']:raise ValueError('Blend absent from verified internal manifest')
   data=z.read(e['blendMember'])
   if hashlib.sha256(data).hexdigest()!=e['blendSha256']:raise ValueError('Blend hash mismatch')
   (directory/'candidate.blend').write_bytes(data)
   report=json.loads(z.read(e['reportMember']))
   rec=next((q for q in report.get('records',[]) if q.get('procedure_id')==e['id']),None)
   if not rec or not rec.get('automated_checks_passed'):raise ValueError('No passed source record in candidate report')
   if 'partial' in str(rec.get('source_scope','')) or rec.get('prototype_source_patch'):raise ValueError('Partial component is not a full source candidate')
   if rec.get('sha256')!=e['blendSha256']:raise ValueError('Worker report does not pin this candidate')
   fidelity=rec.get('source_fidelity',{})
   if not fidelity.get('source_profile_within_tolerance') or fidelity.get('uv0_max_error',1)>.001 or fidelity.get('uv1_max_error',1)>.001 or fidelity.get('uv1_unambiguous_page_mismatches',1)!=0:raise ValueError('Candidate source/UV guards failed')
  (directory/'entry.json').write_text(json.dumps(e))
 shard_manifest=dict(m,entries=selected,shard=shard,stage=stage)
 (w/'shard.json').write_text(json.dumps(shard_manifest,indent=2));return shard_manifest

def inventory_project(project):
 p=Path(project);version=(p/'ProjectSettings/ProjectVersion.txt').read_text();total=0;count=0
 for folder in ('Assets','Packages','ProjectSettings'):
  for f in (p/folder).rglob('*'):
   if f.is_file():total+=f.stat().st_size;count+=1
 return dict(editor_version=version.strip(),source_files=count,source_bytes=total,local_Unity_executed=False,Library_included=False)

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('inspect');a.add_argument('--project',required=True)
 a=sub.add_parser('prepare');a.add_argument('--manifest',required=True);a.add_argument('--project',required=True);a.add_argument('--workspace',required=True);a.add_argument('--shard',type=int,default=0);a.add_argument('--shards',type=int,default=1)
 a=sub.add_parser('extract');a.add_argument('--archive',required=True);a.add_argument('--output',required=True)
 a=sub.add_parser('fetch');a.add_argument('--url-env',required=True);a.add_argument('--sha',required=True);a.add_argument('--output',required=True);a.add_argument('--limit-gib',type=float,default=1)
 args=p.parse_args()
 if args.command=='inspect':print(json.dumps(inventory_project(args.project),indent=2))
 elif args.command=='prepare':
  if not 0<=args.shard<args.shards<=256:raise ValueError('Invalid sharding')
  prepare(args.manifest,args.project,args.workspace,args.shard,args.shards,'validate')
 elif args.command=='extract':extract(args.archive,args.output)
 else:fetch(os.environ[args.url_env],args.sha,args.output,int(args.limit_gib*(1<<30)))
if __name__=='__main__':main()
