"""Remote Linux job watchdog; only targets Unity/Blender in this disposable runner."""
import argparse,json,os,signal,time
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('--deadline',type=float,required=True);p.add_argument('--report',required=True);args=p.parse_args();peak=0;report=Path(args.report);report.parent.mkdir(parents=True,exist_ok=True)
 while True:
  processes=[]
  for directory in Path('/proc').iterdir():
   if not directory.name.isdigit():continue
   try:
    name=(directory/'comm').read_text().strip()
    if name not in ('Unity','blender'):continue
    rss=int((directory/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE');processes.append((int(directory.name),rss,name))
   except (OSError,ValueError,IndexError):continue
  peak=max(peak,max((p[1] for p in processes),default=0));reason=None
  if any(p[1]>12*(1<<30) for p in processes):reason='12GiB process limit'
  if time.time()>args.deadline:reason='270-minute job compute cutoff'
  temporary=report.with_suffix('.tmp');temporary.write_text(json.dumps(dict(checked_at=time.time(),peak_RSS_bytes=peak,stop_reason=reason)));temporary.replace(report)
  if reason:
   for pid,rss,name in processes:
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:pass
   return
  time.sleep(5)
if __name__=='__main__':main()
