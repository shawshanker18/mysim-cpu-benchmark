"""Join final verified mesh archives to explicit Unity source/coordinate/track bindings."""
import argparse,json
from pathlib import Path
from intake import validate_manifest,UNITY_VERSION
def merge(bindings,candidates,expected_count):
 rows={}
 for row in candidates:
  if row['id'] in rows:raise ValueError('Duplicate candidate source; choose a single accepted archive revision')
  rows[row['id']]=row
 if len(rows)!=expected_count:raise ValueError('Candidate inventory is incomplete')
 entries=[]
 for binding in bindings['entries']:
  if binding['id'] not in rows:raise ValueError('Missing candidate for Unity binding')
  row=rows.pop(binding['id'])
  if set(binding)&set(row)-{'id'}:raise ValueError('Candidate may not override source binding fields')
  entries.append(dict(binding,**{k:v for k,v in row.items() if k!='id'}))
 if rows:raise ValueError('Candidate has no explicit Unity binding')
 return validate_manifest(dict(schema=1,unityVersion=UNITY_VERSION,entries=entries,tracks=bindings['tracks'],buildScenes=bindings.get('buildScenes',[])))
def main():
 p=argparse.ArgumentParser();p.add_argument('--bindings',required=True);p.add_argument('--candidates',required=True);p.add_argument('--expected-count',type=int,required=True);p.add_argument('--output',required=True);a=p.parse_args()
 result=merge(json.loads(Path(a.bindings).read_text()),[json.loads(l) for l in Path(a.candidates).read_text().splitlines() if l.strip()],a.expected_count);Path(a.output).write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()
