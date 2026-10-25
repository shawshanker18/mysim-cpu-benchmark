"""Dependency-local sharding and a measured/scenario ETA; no compute dispatch."""
import argparse,collections,hashlib,json,math
from pathlib import Path
from intake import validate_manifest

def estimate(meshes,workers,seconds_per_mesh,cold_seconds=0,assembly_seconds=0,render_seconds=0,final_seconds=0):
 if workers<1 or seconds_per_mesh<0:raise ValueError('Invalid estimate inputs')
 return dict(meshes=meshes,workers=workers,processingHours=meshes*seconds_per_mesh/workers/3600,criticalPathHours=(cold_seconds+meshes*seconds_per_mesh/workers+assembly_seconds+render_seconds+final_seconds)/3600,assumptionSecondsPerMesh=seconds_per_mesh,measured=False)

def plan(m,policy,profile=None,capacity=None,licenses=0):
 validate_manifest(m);target=policy['requestedMachinePool'];capacity=capacity or {}
 verified=capacity.get('verifiedFreeSlots')
 if verified is not None and (not isinstance(verified,int) or verified<0):raise ValueError('Invalid verified capacity')
 github_slots=min(target,verified) if verified is not None else 0;unity_slots=min(github_slots,licenses)
 # Keep validation units track-local. Each source is validated once even when several tracks reference it.
 groups=collections.defaultdict(list)
 for e in m['entries']:groups[(tuple(sorted(e['trackIds'])),e['sourceAsset'])].append(e)
 batches=[];p=profile or {};measured=bool(p.get('measured'))
 seconds=p.get('secondsPerMeshP95',30);bytes_per_mesh=p.get('outputBytesPerMeshP95',4<<20);cold=p.get('coldImportSecondsP95',1200)
 max_count=max(1,min(int((270*60-cold)*.8/max(seconds,1)),int((1<<30)*.8/max(bytes_per_mesh,1))))
 if any(v<=0 for v in (seconds,bytes_per_mesh)) or cold>=270*60:raise ValueError('Invalid worker profile')
 desired=min(len(m['entries']),target*2)
 balance=max(1,math.ceil(len(m['entries'])/desired));batch_size=min(max_count,balance)
 for (tracks,source),entries in sorted(groups.items()):
  entries=sorted(entries,key=lambda e:e['id'])
  for start in range(0,len(entries),batch_size):
   ids=[e['id'] for e in entries[start:start+batch_size]];key=hashlib.sha256((','.join(ids)).encode()).hexdigest()[:16]
   batches.append(dict(id='validate-'+key,stage='validate',ids=ids,sourceAsset=source,tracks=list(tracks),requires=['export-'+key],weightSeconds=cold+len(ids)*seconds))
 assignments={ident:b['id'] for b in batches for ident in b['ids']};nodes=[dict(b,id=b['id'].replace('validate-','export-',1),stage='export',requires=[],unityLicenseRequired=False) for b in batches]+batches
 spots={}
 for track in m['tracks']:
  records=[e for e in m['entries'] if track['id'] in e['trackIds']];dependencies=sorted({assignments[e['id']] for e in records});assembly='assemble-'+track['id'];render='render-'+track['id']
  ranked=sorted(records,key=lambda e:(-len(e.get('riskFlags',[])),e['sourceAsset'],e['id']));selected=[];seen=set()
  for e in ranked:
   group=tuple(e['materialPaths'])
   if group not in seen:selected.append(e['id']);seen.add(group)
   if len(selected)>=policy['spotChecksPerTrack']:break
  for e in ranked:
   if len(selected)>=policy['spotChecksPerTrack']:break
   if e['id'] not in selected:selected.append(e['id'])
  spots[track['id']]=selected
  nodes.append(dict(id='finish-'+track['id'],stage='finish-track',track=track['id'],requires=dependencies,spotChecks=selected,reuseEditorForAssemblyAndRender=True))
 nodes.append(dict(id='build-final',stage='build',requires=['finish-'+t['id'] for t in m['tracks']]))
 all_ids=[i for b in batches for i in b['ids']]
 if len(all_ids)!=len(set(all_ids)) or len(all_ids)!=len(m['entries']):raise ValueError('Nonunique/incomplete plan')
 return dict(schema=1,targetMachines=target,verifiedGithubSlots=github_slots,availableUnityLicenseSlots=unity_slots,renderScope=policy['renderScope'],measuredProfile=measured,resourcePlanReady=bool(measured and github_slots and unity_slots),readyForDispatch=False,maximumMeshCountPerBatch=batch_size,nodes=nodes,spotChecks=spots,acceptance=policy['acceptance'],apiBudget=policy['api'],note='Resource planning does not prove input, license or runtime readiness. A completed track may advance independently; another track failure does not block unrelated tracks. The final build waits for every required render and actual acceptance remains separate.')

def ready_nodes(plan,states):
 return [n for n in plan['nodes'] if states.get(n['id'],'pending')=='pending' and all(states.get(dep)=='complete' for dep in n['requires'])]

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--manifest',required=True);a.add_argument('--policy',required=True);a.add_argument('--profile');a.add_argument('--capacity');a.add_argument('--licenses',type=int,default=0);a.add_argument('--output',required=True);x=a.parse_args()
 result=plan(json.loads(Path(x.manifest).read_text()),json.loads(Path(x.policy).read_text()),json.loads(Path(x.profile).read_text()) if x.profile else None,json.loads(Path(x.capacity).read_text()) if x.capacity else None,x.licenses);Path(x.output).write_text(json.dumps(result,indent=2))
