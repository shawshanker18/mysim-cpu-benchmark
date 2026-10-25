"""Create one exact node input after its dependencies are durable; no auto-dispatch."""
import argparse,hashlib,json
from pathlib import Path
from intake import validate_manifest
def freeze(manifest,graph,node_id,project_sha,receipts,lease_id=None):
 validate_manifest(manifest);node=next(n for n in graph['nodes'] if n['id']==node_id);stage=node['stage']
 if stage!='export' and not lease_id:raise ValueError('Reserve actual Unity capacity before freezing this node')
 if stage in ('export','validate'):entries=[e for e in manifest['entries'] if e['id'] in node['ids']];tracks=[t for t in manifest['tracks'] if any(t['id'] in e['trackIds'] for e in entries)]
 elif stage=='finish-track':entries=[e for e in manifest['entries'] if node['track'] in e['trackIds']];tracks=[dict(t,spotCheckIds=node['spotChecks']) for t in manifest['tracks'] if t['id']==node['track']]
 else:entries=manifest['entries'];tracks=manifest['tracks']
 inputs=[];dependencies=list(node['requires'])
 if stage=='build':dependencies+=[n['id'] for n in graph['nodes'] if n['stage']=='validate']
 for dependency in dict.fromkeys(dependencies):
  if dependency not in receipts or not receipts[dependency].get('verified'):raise ValueError('Dependency not yet hash verified: '+dependency)
  record=receipts[dependency];inputs.append(dict(stage=record['stage'],url=record['url'],sha256=record['sha256']))
 if stage=='finish-track' and any(not t.get('renderScene') or not t.get('renderCameraPaths') for t in tracks):raise ValueError('Actual scene/camera bindings required before track rendering')
 subset=dict(manifest,entries=entries,tracks=tracks)
 # Shared assets can reference other tracks outside this node; keep membership only within this verified subset.
 allowed={t['id'] for t in tracks};subset['entries']=[dict(e,trackIds=[i for i in e['trackIds'] if i in allowed]) for e in entries];validate_manifest(subset)
 return dict(schema=1,id=node_id,stage=stage,track=node.get('track',''),manifest=subset,projectSha256=project_sha,packageInputs=inputs,leaseId=lease_id)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--graph',required=True);p.add_argument('--node',required=True);p.add_argument('--project-sha',required=True);p.add_argument('--receipts',required=True);p.add_argument('--lease');p.add_argument('--output',required=True);a=p.parse_args()
 value=freeze(json.loads(Path(a.manifest).read_text()),json.loads(Path(a.graph).read_text()),a.node,a.project_sha,json.loads(Path(a.receipts).read_text()),a.lease);data=json.dumps(value,sort_keys=True,indent=2).encode();Path(a.output).write_bytes(data);print(hashlib.sha256(data).hexdigest())
