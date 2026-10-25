"""Durable, shared REST request budget. No credential rotation or automatic POST retries."""
import contextlib,json,os,sqlite3,time,urllib.request,urllib.error,urllib.parse
from pathlib import Path

class Deferred(RuntimeError):
 def __init__(self,reason,retry_at):super().__init__(reason);self.retry_at=retry_at
class UncertainMutation(RuntimeError):pass

class Budget:
 def __init__(self,path,limit=4000,hard_limit=5000,interval=1.,reserve_remaining=1000,clock=time.time):
  if not 1<=limit<=hard_limit<=5000:raise ValueError('Cannot exceed requested5000/hour limit')
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.limit=limit;self.interval=interval;self.clock=clock;self.reserve_remaining=reserve_remaining
  with self.connect() as db:
   db.executescript('CREATE TABLE IF NOT EXISTS requests(ts REAL, method TEXT, account TEXT); CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value REAL); CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,etag TEXT,body TEXT);')
 @contextlib.contextmanager
 def connect(self):
  db=sqlite3.connect(self.path,timeout=30)
  try:
   with db:yield db
  finally:db.close()
 def reserve(self,account,method):
  now=self.clock()
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');db.execute('DELETE FROM requests WHERE ts<=?',(now-3600,))
   states=dict(db.execute('SELECT key,value FROM state'));blocked=max(states.get('global_blocked',0),states.get('blocked:'+account,0));recent=db.execute('SELECT MIN(ts),MAX(ts),COUNT(*) FROM requests').fetchone()
   if now<blocked:raise Deferred('GitHub cooldown active; no alternate-account retry',blocked)
   if recent[2]>=self.limit:raise Deferred('Local rolling-hour API budget exhausted',recent[0]+3600)
   if recent[1] is not None and now<recent[1]+self.interval:raise Deferred('Serial API pacing',recent[1]+self.interval)
   if method not in ('GET','HEAD') and 'last_mutation' in states and now<states['last_mutation']+1:raise Deferred('Mutation spacing',states['last_mutation']+1)
   db.execute('INSERT INTO requests VALUES(?,?,?)',(now,method,account))
   if method not in ('GET','HEAD'):db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('last_mutation',now))
 def observe(self,account,status,headers):
  h={k.lower():v for k,v in headers.items()};now=self.clock();until=0;scope='blocked:'+account
  if 'x-ratelimit-remaining' in h and int(h['x-ratelimit-remaining'])<=self.reserve_remaining:until=float(h.get('x-ratelimit-reset',now+60))+1
  elif status in (403,429):until=now+max(60,float(h.get('retry-after','60')));scope='global_blocked'
  elif 'retry-after' in h:until=now+float(h['retry-after']);scope='global_blocked'
  if until:
   with self.connect() as db:
    old=db.execute('SELECT value FROM state WHERE key=?',(scope,)).fetchone();db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(scope,max(until,old[0] if old else 0)))
 def cached(self,key):
  with self.connect() as db:return db.execute('SELECT etag,body FROM cache WHERE key=?',(key,)).fetchone()
 def cache(self,key,etag,body):
  with self.connect() as db:db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(key,etag,body))

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

class GitHub:
 def __init__(self,budget,account,token,transport=None):
  self.budget=budget;self.account=account;self.token=token
  self.transport=transport or (lambda request:urllib.request.build_opener(NoRedirect).open(request,timeout=30))
 def request(self,method,path,payload=None):
  url='https://api.github.com/'+path.lstrip('/')
  if urllib.parse.urlsplit(url).netloc!='api.github.com':raise ValueError('Only GitHub API control-plane requests')
  key=self.account+':'+url;cached=self.budget.cached(key) if method=='GET' else None
  headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'MySim-rate-budgeted-unity-coordinator'}
  if cached and cached[0]:headers['If-None-Match']=cached[0]
  try:self.budget.reserve(self.account,method)
  except Deferred as e:
   if str(e) not in ('Serial API pacing','Mutation spacing'):raise
   time.sleep(max(.01,e.retry_at-self.budget.clock()));self.budget.reserve(self.account,method)
  req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers=headers,method=method)
  try:
   response=self.transport(req);status=response.status;h=dict(response.headers);body=response.read().decode();response.close()
  except urllib.error.HTTPError as e:
   status=e.code;h=dict(e.headers);body=e.read().decode(errors='replace')
  except (OSError,TimeoutError) as e:
   if method not in ('GET','HEAD'):raise UncertainMutation('Dispatch outcome unknown; reconcile immutable dispatch ID before retry') from e
   raise
  self.budget.observe(self.account,status,h)
  if status in (403,429):raise Deferred('GitHub rate/permission response; do not loop or switch credentials',max(self.budget.clock()+60,float({k.lower():v for k,v in h.items()}.get('x-ratelimit-reset',0))+1))
  if status==304:
   if not cached:raise ValueError('304 without local cached representation')
   return json.loads(cached[1])
  if 300<=status<400:
   if method not in ('GET','HEAD'):raise UncertainMutation('Mutative redirect requires canonical repository reconciliation')
   raise RuntimeError('Canonical repository URL must be updated; no hidden redirected API requests')
  if not 200<=status<300:raise RuntimeError('GitHub API returned HTTP '+str(status))
  if method=='GET':self.budget.cache(key,{k.lower():v for k,v in h.items()}.get('etag',''),body)
  return json.loads(body) if body else None
