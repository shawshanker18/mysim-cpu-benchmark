"""Create a private immutable source snapshot; no Unity execution, no upload."""
import argparse,gzip,json,tarfile
from pathlib import Path
from intake import digest,UNITY_VERSION
def pack(project,output,catalog_assets=()):
 project=Path(project).resolve();output=Path(output).resolve()
 if output.is_relative_to(project):raise ValueError('Snapshot must be outside source project')
 if output.exists():raise ValueError('Refuse to overwrite a snapshot')
 if f'm_EditorVersion: {UNITY_VERSION}' not in (project/'ProjectSettings/ProjectVersion.txt').read_text():raise ValueError('Wrong source Unity version')
 deps=json.loads((project/'Packages/manifest.json').read_text()).get('dependencies',{})
 if any(str(v).startswith('file:') for v in deps.values()):raise ValueError('Local package dependencies need explicit snapshot inclusion first')
 if catalog_assets:
  files=set(p for folder in ('Packages','ProjectSettings') for p in (project/folder).rglob('*') if p.is_file())
  for name in catalog_assets:
   from intake import safe_path
   path=safe_path(project,name)
   if not name.startswith('Assets/RealRacing/Source/') or path.suffix.lower()!='.fbx' or not path.is_file():raise ValueError('Catalogue snapshot accepts explicit original source FBX files only')
   if not Path(str(path)+'.meta').is_file():raise ValueError('Original source meta/GUID missing')
   files.update([path,Path(str(path)+'.meta')])
   for parent in path.parents:
    if parent==project:break
    meta=Path(str(parent)+'.meta')
    if meta.is_file():files.add(meta)
  files=sorted(files)
 else:files=sorted(p for folder in ('Assets','Packages','ProjectSettings') for p in (project/folder).rglob('*') if p.is_file())
 if any(p.is_symlink() for p in files):raise ValueError('Snapshot links require explicit dependency handling')
 size=sum(p.stat().st_size for p in files)
 if size>10*(1<<30):raise ValueError('Full project exceeds initial remote disk budget: prepare a remote dependency-closed track snapshot, do not silently omit assets')
 output.parent.mkdir(parents=True,exist_ok=True)
 with output.open('wb') as dst,gzip.GzipFile(fileobj=dst,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w|') as tar:
  for p in files:
   info=tar.gettarinfo(str(p),str(p.relative_to(project)).replace('\\','/'));info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=''
   with p.open('rb') as src:tar.addfile(info,src)
 proof=dict(sha256=digest(output),bytes=output.stat().st_size,expandedBytes=size,fileCount=len(files),unityVersion=UNITY_VERSION,scope='source_inventory_only' if catalog_assets else 'complete_project_snapshot',uploaded=False,localUnityExecuted=False)
 output.with_suffix(output.suffix+'.json').write_text(json.dumps(proof,indent=2));return proof
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--output',required=True);p.add_argument('--catalog-asset',action='append',default=[]);a=p.parse_args();print(json.dumps(pack(a.project,a.output,a.catalog_asset),indent=2))
