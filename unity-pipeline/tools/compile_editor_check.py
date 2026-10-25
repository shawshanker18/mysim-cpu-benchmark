"""Compile Editor code against installed reference DLLs; DOES NOT launch Unity/import assets."""
import argparse,subprocess
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('--unity-data',required=True);args=p.parse_args();data=Path(args.unity_data);root=Path(__file__).parents[1];output=root/'validation';output.mkdir(exist_ok=True)
 sdk=data/'DotNetSdk';compiler=next(sdk.glob('sdk/*/Roslyn/bincore/csc.dll'));runtime=sdk/'dotnet.exe'
 refs=list((data/'UnityReferenceAssemblies/unity-4.8-api').glob('*.dll'))+list((data/'UnityReferenceAssemblies/unity-4.8-api/Facades').glob('*.dll'))+list((data/'Managed/UnityEngine').glob('*.dll'))+list((data/'Managed/UnityEditor').glob('*.dll'))
 assert refs and runtime.exists();rsp=output/'compile.rsp';rsp.write_text('\n'.join(['/nologo','/target:library','/nostdlib+','/langversion:9','/out:"'+str(output/'RemoteCI.syntaxcheck.dll')+'"']+['/reference:"'+str(r)+'"' for r in refs]+['"'+str(root/'Editor/RemoteCI.cs')+'"']),encoding='utf-8')
 result=subprocess.run([str(runtime),str(compiler),'@'+str(rsp)],capture_output=True,text=True,timeout=90);print(result.stdout);print(result.stderr);raise SystemExit(result.returncode)
if __name__=='__main__':main()
