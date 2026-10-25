"""Persistent node/seat reservations. A timeout never frees an uncertain dispatch."""
import contextlib,hashlib,json,sqlite3,time
from pathlib import Path
class Registry:
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.connect() as db:db.executescript('CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,payload TEXT,state TEXT,owner TEXT,run_id TEXT,receipt_sha TEXT); CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);')
 @contextlib.contextmanager
 def connect(self):
  db=sqlite3.connect(self.path,timeout=30)
  try:
   with db:yield db
  finally:db.close()
 def initialize(self,plan):
  digest=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');old=db.execute("SELECT value FROM metadata WHERE key='plan'").fetchone()
   if old and old[0]!=digest:raise ValueError('Different graph requires explicit reconciliation, not resetting active work')
   db.execute("INSERT OR IGNORE INTO metadata VALUES('plan',?)",(digest,))
   for n in plan['nodes']:db.execute('INSERT OR IGNORE INTO nodes VALUES(?,?,?,?,?,?)',(n['id'],json.dumps(n),'pending',None,None,None))
 def claim(self,owner,free_slots,license_slots,target=190,node_id=None):
  if not 0<target<=190 or free_slots<0 or license_slots<0:raise ValueError('Invalid verified resource inventory')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');rows=list(db.execute('SELECT id,payload,state,owner FROM nodes'));active=[r for r in rows if r[2] in ('reserved','submitted','uncertain')]
   # free_slots must already subtract all actual repository jobs, including other workflows.
   pending_owner=sum(r[3]==owner and r[2] in ('reserved','uncertain') for r in active)
   if len(active)>=target or pending_owner>=free_slots:return None
   states={r[0]:r[2] for r in rows}
   unity_active=sum(json.loads(r[1])['stage']!='export' for r in active)
   priority={'finish-track':0,'build':1,'validate':2,'export':3}
   for ident,payload,state,_ in sorted(rows,key=lambda r:priority.get(json.loads(r[1])['stage'],9)):
    if node_id is not None and ident!=node_id:continue
    n=json.loads(payload)
    if n['stage']!='export' and unity_active>=license_slots:continue
    if state=='pending' and all(states.get(dep)=='complete' for dep in n['requires']):
     db.execute("UPDATE nodes SET state='reserved',owner=? WHERE id=?",(owner,ident));return n
  return None
 def submitted(self,ident,run_id):
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT state,run_id FROM nodes WHERE id=?',(ident,)).fetchone()
   if not row or row[0] not in ('reserved','uncertain','submitted') or (row[1] and row[1]!=str(run_id)):raise ValueError('Conflicting/repeated dispatch identity')
   db.execute("UPDATE nodes SET state='submitted',run_id=? WHERE id=?",(str(run_id),ident))
 def uncertain(self,ident):
  with self.connect() as db:
   row=db.execute('SELECT state FROM nodes WHERE id=?',(ident,)).fetchone()
   if not row or row[0]!='reserved':raise ValueError('Only an unconfirmed reservation can become uncertain')
   db.execute("UPDATE nodes SET state='uncertain' WHERE id=?",(ident,))
 def complete(self,ident,github_status,receipt):
  if github_status!='completed' or not receipt.get('passed') or len(receipt.get('sha256',''))!=64:raise ValueError('Need terminal GitHub state and verified receipt')
  with self.connect() as db:
   row=db.execute('SELECT state FROM nodes WHERE id=?',(ident,)).fetchone()
   if not row or row[0] not in ('submitted','uncertain'):raise ValueError('Node not dispatched')
   db.execute("UPDATE nodes SET state='complete',receipt_sha=? WHERE id=?",(receipt['sha256'],ident))
 def fail(self,ident,github_status):
  if github_status!='completed':raise ValueError('Do not free running or finalizing jobs')
  with self.connect() as db:db.execute("UPDATE nodes SET state='failed' WHERE id=?",(ident,))
