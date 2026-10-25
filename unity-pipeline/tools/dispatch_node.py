"""One reserved, immutable dispatch through the shared API governor. No token rotation."""
import argparse,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from api_budget import Budget,GitHub
from chain_state import Registry

def dispatch(args):
 capacity=json.loads(Path(args.capacity).read_text());graph=json.loads(Path(args.graph).read_text());spec=Path(args.spec);node=json.loads(spec.read_text())
 if time.time()-capacity['observedAtUnix']>120 or capacity['observedAtUnix']>time.time()+5:raise ValueError('Fresh actual capacity snapshot required')
 owner=capacity['owners'][args.owner]
 if not owner.get('apiVerified') or not owner.get('repo') or not capacity.get('externalApiActorsBudgeted'):raise ValueError('Reconcile repository capacity and all competing API controllers first')
 if not re.fullmatch('[a-zA-Z0-9_.-]{1,100}',args.ref) or re.fullmatch('[a-f0-9]{40}',args.ref):raise ValueError('Immutable named tag required')
 blob=subprocess.run(['git','show',args.ref+':unity-inputs/'+node['id']+'.json'],cwd=args.frozen_repo,capture_output=True,check=True).stdout
 if hashlib.sha256(blob).digest()!=hashlib.sha256(spec.read_bytes()).digest():raise ValueError('Node differs from exact immutable Git blob')
 if not args.apply:return dict(state='DRY_RUN_NO_DISPATCH',node=node['id'],target=graph['targetMachines'])
 sys.path.insert(0,str(Path(args.launch_root)/'work'));from mysim_launch_lock import exclusive_launch_lock
 with exclusive_launch_lock(args.launch_root,timeout=45):
  registry=Registry(args.registry);registry.initialize(graph)
  token=subprocess.run(['gh','auth','token','--user',args.owner],capture_output=True,text=True,check=True).stdout.strip();api=GitHub(Budget(args.api_budget),args.owner,token)
  ref=api.request('GET','repos/'+owner['repo']+'/git/ref/tags/'+args.ref)
  local=subprocess.run(['git','rev-parse',args.ref+'^{commit}'],cwd=args.frozen_repo,capture_output=True,text=True,check=True).stdout.strip()
  if ref['object']['type']!='commit' or ref['object']['sha']!=local:raise ValueError('Remote immutable tag differs from prepared commit')
  claimed=registry.claim(args.owner,owner['freeSlots'],capacity.get('verifiedUnityLicenseSlots',0),min(190,graph['targetMachines']),node['id'])
  if not claimed:return dict(state='WAITING_CAPACITY_OR_DEPENDENCIES',node=node['id'])
  dispatch_id=node['id']+'-'+hashlib.sha256(spec.read_bytes()).hexdigest()[:16]
  try:api.request('POST','repos/'+owner['repo']+'/actions/workflows/unity-node.yml/dispatches',dict(ref=args.ref,inputs=dict(node_id=node['id'],spec_sha256=hashlib.sha256(spec.read_bytes()).hexdigest(),dispatch_id=dispatch_id)))
  except Exception:
   registry.uncertain(node['id']);raise
  # A204 is accepted, not running. Keep its reservation until a run is reconciled by dispatch_id/head SHA.
  registry.uncertain(node['id']);return dict(state='ACCEPTED_AWAITING_RUN_RECONCILIATION',node=node['id'],dispatch_id=dispatch_id,head_sha=local)

if __name__=='__main__':
 p=argparse.ArgumentParser()
 for name in ('capacity','graph','spec','owner','ref','frozen-repo','registry','api-budget','launch-root'):p.add_argument('--'+name,required=True)
 p.add_argument('--apply',action='store_true');a=p.parse_args();print(json.dumps(dispatch(a)))
