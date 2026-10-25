import copy,hashlib,io,json,sqlite3,tempfile,unittest,urllib.error
from pathlib import Path
from test_pipeline import manifest
from api_budget import Budget,GitHub,Deferred,UncertainMutation
from fast_plan import plan,ready_nodes,estimate
from chain_state import Registry
class Clock:
 def __init__(self):self.time=10000
 def __call__(self):return self.time
class Response:
 def __init__(self,status=200,headers=None,body=b'{}'):self.status=status;self.headers=headers or {};self.body=body
 def read(self):return self.body
 def close(self):pass
class FastPathTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.addCleanup(self.temp.cleanup);self.clock=Clock()
 def test_global_hour_budget_survives_restart_and_different_accounts(self):
  path=self.root/'budget.db';b=Budget(path,limit=2,interval=0,clock=self.clock);b.reserve('one','GET');b.reserve('two','GET')
  with self.assertRaises(Deferred):Budget(path,limit=2,interval=0,clock=self.clock).reserve('three','GET')
  self.clock.time+=3601;b.reserve('one','GET')
 def test_rate_reset_honored_without_alternate_token(self):
  b=Budget(self.root/'b.db',interval=0,clock=self.clock);b.observe('one',403,{'X-RateLimit-Remaining':'0','X-RateLimit-Reset':'11000'})
  with self.assertRaises(Deferred):b.reserve('one','GET')
  self.clock.time=11002;b.reserve('one','GET')
 def test_secondary_retry_after_blocks_entire_coordinator(self):
  b=Budget(self.root/'b.db',interval=0,clock=self.clock);b.observe('one',429,{'retry-after':'120'})
  with self.assertRaises(Deferred):b.reserve('another','GET')
 def test_uncertain_dispatch_is_not_retried(self):
  b=Budget(self.root/'b.db',interval=0,clock=self.clock)
  def timeout(req):raise TimeoutError('simulated')
  with self.assertRaises(UncertainMutation):GitHub(b,'one','test-token',timeout).request('POST','repos/owner/repo/actions/workflows/x/dispatches',{})
  with b.connect() as db:self.assertEqual(db.execute('select count(*) from requests').fetchone()[0],1)
 def test_conditional_requests_still_count_local_budget(self):
  b=Budget(self.root/'b.db',interval=0,clock=self.clock)
  client=GitHub(b,'one','token',lambda r:Response(headers={'ETag':'"first"'},body=b'{"state":"running"}'));self.assertEqual(client.request('GET','repos/o/r')['state'],'running')
  def unchanged(request):
   self.assertEqual(request.get_header('If-none-match'),'"first"');raise urllib.error.HTTPError(request.full_url,304,'unchanged',{},io.BytesIO(b''))
  client.transport=unchanged;self.assertEqual(client.request('GET','repos/o/r')['state'],'running')
  with b.connect() as db:self.assertEqual(db.execute('select count(*) from requests').fetchone()[0],2)
 def test_conservative_remaining_reserve_stops_more_calls(self):
  b=Budget(self.root/'b.db',interval=0,clock=self.clock);b.observe('one',200,{'x-ratelimit-remaining':'999','x-ratelimit-reset':'12000'})
  with self.assertRaises(Deferred):b.reserve('one','GET')
 def test_first_track_advances_without_global_barrier(self):
  m=manifest();second=copy.deepcopy(m['entries'][0]);second.update(id='b'*24,sourceMesh='other',trackIds=['other']);m['entries'].append(second);m['tracks'].append(dict(m['tracks'][0],id='other',sourcePrefab='Assets/Other.prefab'))
  policy=json.loads((Path(__file__).parents[1]/'execution-policy.json').read_text());graph=plan(m,policy);self.assertFalse(graph['readyForDispatch']);self.assertEqual(graph['targetMachines'],190)
  states={n['id']:'pending' for n in graph['nodes']};track=next(n for n in graph['nodes'] if n['id']=='finish-track26')
  for dep in track['requires']:states[dep]='complete'
  self.assertIn('finish-track26',[n['id'] for n in ready_nodes(graph,states)]);self.assertNotIn('finish-other',[n['id'] for n in ready_nodes(graph,states)])
 def test_uncertain_lease_blocks_duplicate_after_restart(self):
  p=self.root/'state.db';r=Registry(p);r.initialize({'nodes':[dict(id='a',stage='validate',requires=[])]});self.assertEqual(r.claim('one',1,1)['id'],'a');r.uncertain('a');self.assertIsNone(Registry(p).claim('one',1,1))
 def test_cpu_export_does_not_consume_unity_license(self):
  r=Registry(self.root/'state.db');r.initialize({'nodes':[dict(id='e',stage='export',requires=[]),dict(id='v',stage='validate',requires=['e'])]});self.assertEqual(r.claim('one',1,0)['id'],'e');r.submitted('e',1)
  with self.assertRaises(ValueError):r.complete('e','in_progress',dict(passed=True,sha256='a'*64))
  r.complete('e','completed',dict(passed=True,sha256='a'*64));self.assertIsNone(r.claim('one',1,0));self.assertEqual(r.claim('one',1,1)['id'],'v')
 def test_eta_is_explicit_scenario_not_a_promise(self):
  x=estimate(98572,190,60);self.assertAlmostEqual(x['processingHours'],8.647,places=2);self.assertFalse(x['measured'])
if __name__=='__main__':unittest.main()
