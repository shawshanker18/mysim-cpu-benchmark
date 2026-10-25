// Installed only in an isolated remote project. Never run against the working source project.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;
using Unity.Collections;
using Debug = UnityEngine.Debug;

namespace MySim.Remote {
 [Serializable] public class Manifest { public int schema; public string unityVersion; public Entry[] entries; public Track[] tracks; public string[] buildScenes; }
 [Serializable] public class Track { public string id, sourcePrefab, sourcePrefabSha256; }
 [Serializable] public class Entry {
  public string id, sourceAsset, sourceSha256, sourceMesh, sourceFileId;
  public string[] trackIds, materialPaths; public float[] sourceToUnity, lodHeights;
 }
 [Serializable] public class Part { public string file, sha256, name; public int lod, vertices, triangles; public string[] uvNames; }
 [Serializable] public class MeshIndex { public int schema; public string id; public Part[] parts, collision; }
 [Serializable] public class Result { public bool passed; public string stage, unityVersion, detail; public string[] ids; public string[] tracks; public bool graphicsAppearanceValidated=false; public bool finalArtisticUnityAccepted=false; }
 [Serializable] public class CatalogueItem { public string asset, assetSha256, mesh, guid, fileId; public int vertices, triangles, uvChannels; public Vector3 boundsCenter, boundsSize; }
 [Serializable] public class Catalogue { public string unityVersion; public List<CatalogueItem> meshes = new List<CatalogueItem>(); }

 public static class RemoteCI {
  const string Version = "6000.3.26f1", Generated = "Assets/MySimRemoteGenerated";
  static string Root, Output; static Manifest Config;
  static readonly List<string> Passed = new List<string>();
  static string Arg(string name, string fallback=null) { var a=Environment.GetCommandLineArgs(); int i=Array.IndexOf(a,name); return i>=0 && i+1<a.Length?a[i+1]:fallback; }
  static void Require(bool ok,string message) { if(!ok) throw new InvalidOperationException(message); }
  static void Budget() { Require(Process.GetCurrentProcess().WorkingSet64 <= 12L*1024*1024*1024,"12GiB Unity process safety guard"); }
  static bool Finite(float f) { return !float.IsNaN(f)&&!float.IsInfinity(f); }
  static string Full(string path) {
   Require(!string.IsNullOrWhiteSpace(path)&&!Path.IsPathRooted(path)&&!path.Contains("\\")&&!path.Split('/').Contains(".."),"Unsafe project-relative asset path");
   return Path.GetFullPath(path);
  }
  static string Hash(string path) { using(var h=SHA256.Create()) using(var f=File.OpenRead(path)) return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToLowerInvariant(); }
  static string Key(UnityEngine.Object obj) { if(!obj)return "null"; Require(AssetDatabase.TryGetGUIDAndLocalFileIdentifier(obj,out string guid,out long id),"Object has no stable source GUID/fileID"); return guid+":"+id; }
  static Matrix4x4 Matrix(Entry e) { Require(e.sourceToUnity!=null&&e.sourceToUnity.Length==16,"Explicit source-to-Unity binding required"); var m=new Matrix4x4(); for(int i=0;i<16;i++){Require(Finite(e.sourceToUnity[i]),"Nonfinite transform");m[i/4,i%4]=e.sourceToUnity[i];} Require(Mathf.Abs(m.determinant)>1e-15f,"Singular binding");return m; }

  public static void Run() {
   string stage=Arg("-mysimStage","validate"); Output=Path.GetFullPath(Arg("-mysimOutputRoot","unity-out")); Directory.CreateDirectory(Output);
   try {
    Require(Application.unityVersion==Version,"Project must run with exact pinned Unity version"); Budget();
    if(stage=="inventory") { Inventory(); WriteReport(stage,new string[0],"Source identifiers only; no candidate accepted");return; }
    Root=Path.GetFullPath(Arg("-mysimInputRoot")??throw new InvalidOperationException("Missing intake root"));
    Config=JsonUtility.FromJson<Manifest>(File.ReadAllText(Arg("-mysimManifest")??Path.Combine(Root,"shard.json")));
    Require(Config.schema==1&&Config.unityVersion==Version&&Config.entries!=null,"Invalid intake manifest");
    if(stage=="validate") Validate();
    else if(stage=="assemble") Assemble(Arg("-mysimTrack")??throw new InvalidOperationException("Track ID required"));
    else if(stage=="build") Build();
    else throw new InvalidOperationException("Unsupported stage");
    WriteReport(stage,stage=="assemble"?new[]{Arg("-mysimTrack")}:new string[0],"Structural candidate checks passed; graphics/runtime acceptance remains pending");
   } catch(Exception ex) {
    File.WriteAllText(Path.Combine(Output,"report.json"),JsonUtility.ToJson(new Result{passed=false,stage=stage,unityVersion=Application.unityVersion,ids=Passed.ToArray(),detail=ex.ToString()},true));
    Debug.LogException(ex); throw;
   }
  }
  static void WriteReport(string stage,string[] tracks,string detail) { File.WriteAllText(Path.Combine(Output,"report.json"),JsonUtility.ToJson(new Result{passed=true,stage=stage,unityVersion=Version,ids=Passed.ToArray(),tracks=tracks,detail=detail},true)); }

  static void Inventory() {
   var result=new Catalogue();
   foreach(string guid in AssetDatabase.FindAssets("t:Model",new[]{"Assets/RealRacing/Source"})) {
    Budget();string path=AssetDatabase.GUIDToAssetPath(guid);string sha=Hash(Full(path));
    foreach(var mesh in AssetDatabase.LoadAllAssetsAtPath(path).OfType<Mesh>()) {
     Require(AssetDatabase.TryGetGUIDAndLocalFileIdentifier(mesh,out string mg,out long id),"Mesh source identity missing");
     int uv=0;for(int i=0;i<8;i++)if(mesh.HasVertexAttribute((VertexAttribute)((int)VertexAttribute.TexCoord0+i)))uv++;
     result.meshes.Add(new CatalogueItem{asset=path,assetSha256=sha,mesh=mesh.name,guid=mg,fileId=id.ToString(),vertices=mesh.vertexCount,triangles=(int)Enumerable.Range(0,mesh.subMeshCount).Sum(i=>(long)mesh.GetIndexCount(i))/3,uvChannels=uv,boundsCenter=mesh.bounds.center,boundsSize=mesh.bounds.size});
    }
   }
   File.WriteAllText(Path.Combine(Output,"source-catalogue.json"),JsonUtility.ToJson(result,true));
  }
  static Mesh Source(Entry e) {
   Require(e.sourceAsset.StartsWith("Assets/",StringComparison.Ordinal)&&Hash(Full(e.sourceAsset))==e.sourceSha256,"Source asset hash mismatch: "+e.id);
   var matches=AssetDatabase.LoadAllAssetsAtPath(e.sourceAsset).OfType<Mesh>().Where(m=>m.name==e.sourceMesh).ToArray();
   if(!string.IsNullOrEmpty(e.sourceFileId)) matches=matches.Where(m=>{AssetDatabase.TryGetGUIDAndLocalFileIdentifier(m,out string g,out long id);return id.ToString()==e.sourceFileId;}).ToArray();
   Require(matches.Length==1,"Source name/fileID is missing or ambiguous: "+e.id);return matches[0];
  }
  static Mesh Read(Entry e,Part p) {
   Budget();string path=Path.Combine(Root,"meshes",e.id,p.file);Require(Path.GetFileName(p.file)==p.file&&Hash(path)==p.sha256,"Exchange hash/path mismatch");
   using(var f=new BinaryReader(File.OpenRead(path))) {
    Require(System.Text.Encoding.ASCII.GetString(f.ReadBytes(8))=="MYSMESH1","Wrong mesh exchange format");
    int n=f.ReadInt32(), uv=f.ReadInt32(), subs=f.ReadInt32(), tangents=f.ReadInt32(), colors=f.ReadInt32();
    Require(n>0&&n<=3000000&&uv>=0&&uv<=8&&subs==e.materialPaths.Length&&subs>0&&subs<=128&&(tangents==0||tangents==1)&&(colors==0||colors==1),"Mesh resource/channel/material inventory invalid");
    Require(n==p.vertices&&p.uvNames.Length==uv,"Declared mesh inventory changed");
    var vertices=new Vector3[n];var normals=new Vector3[n];var ts=tangents==1?new Vector4[n]:null;var cs=colors==1?new Color[n]:null;
    var uvs=new List<Vector2>[uv];for(int j=0;j<uv;j++)uvs[j]=new List<Vector2>(n);
    Matrix4x4 matrix=Matrix(e), normal=matrix.inverse.transpose;bool flip=matrix.determinant<0;
    Func<float> read=()=>{float value=f.ReadSingle();Require(Finite(value),"Nonfinite exchange data");return value;};
    for(int i=0;i<n;i++) {
     vertices[i]=matrix.MultiplyPoint3x4(new Vector3(read(),read(),read()));normals[i]=normal.MultiplyVector(new Vector3(read(),read(),read())).normalized;Require(Finite(vertices[i].x)&&Finite(vertices[i].y)&&Finite(vertices[i].z)&&normals[i].sqrMagnitude>.5f,"Invalid transformed geometry/normal");
     for(int j=0;j<uv;j++)uvs[j].Add(new Vector2(read(),read()));
     if(tangents==1){var t=matrix.MultiplyVector(new Vector3(read(),read(),read())).normalized;float w=read();ts[i]=new Vector4(t.x,t.y,t.z,w*(flip?-1:1));}
     if(colors==1)cs[i]=new Color(read(),read(),read(),read());
    }
    var mesh=new Mesh{name=e.id+"_"+p.lod+"_"+p.file,indexFormat=n>65535?IndexFormat.UInt32:IndexFormat.UInt16};mesh.vertices=vertices;mesh.normals=normals;
    for(int j=0;j<uv;j++){mesh.SetUVs(j,uvs[j]);var restored=new List<Vector2>();mesh.GetUVs(j,restored);Require(restored.SequenceEqual(uvs[j]),"Unity UV channel altered, including encoded UV1");}
    if(ts!=null)mesh.tangents=ts;if(cs!=null)mesh.colors=cs;mesh.subMeshCount=subs;long total=0;
    for(int j=0;j<subs;j++){int count=f.ReadInt32();Require(count>=0&&count%3==0&&count<=n*12,"Triangle budget");var indices=new int[count];for(int k=0;k<count;k++){indices[k]=f.ReadInt32();Require(indices[k]>=0&&indices[k]<n,"Invalid triangle index");}if(flip)for(int k=0;k<count;k+=3){int a=indices[k];indices[k]=indices[k+2];indices[k+2]=a;}mesh.SetTriangles(indices,j,false);total+=count/3;}
    Require(total==p.triangles&&f.BaseStream.Position==f.BaseStream.Length,"Triangle inventory/trailing data mismatch");mesh.RecalculateBounds();return mesh;
   }
  }
  static string Cell(Vector3 p,float t,int x=0,int y=0,int z=0) { return ((long)Math.Floor(p.x/t)+x)+","+((long)Math.Floor(p.y/t)+y)+","+((long)Math.Floor(p.z/t)+z); }
  static Mesh ReadableSource(Mesh original) {
   // Editor-only snapshot avoids changing ModelImporter.isReadable or reimporting/rewriting UVs.
   var copy=new Mesh{indexFormat=original.indexFormat};
   using(var snapshot=MeshUtility.AcquireReadOnlyMeshData(original)) {
    var data=snapshot[0];using(var vertices=new NativeArray<Vector3>(data.vertexCount,Allocator.Temp)){data.GetVertices(vertices);copy.vertices=vertices.ToArray();}
    for(int channel=0;channel<8;channel++)if(original.HasVertexAttribute((VertexAttribute)((int)VertexAttribute.TexCoord0+channel))) {
     Require(original.GetVertexAttributeDimension((VertexAttribute)((int)VertexAttribute.TexCoord0+channel))==2,"Source has higher-dimensional UVs; require dedicated exchange support, never truncate");
     using(var uvs=new NativeArray<Vector2>(data.vertexCount,Allocator.Temp)){data.GetUVs(channel,uvs);copy.SetUVs(channel,uvs.ToArray());}
    }
    copy.subMeshCount=data.subMeshCount;
    for(int sub=0;sub<data.subMeshCount;sub++){var desc=data.GetSubMesh(sub);Require(desc.topology==MeshTopology.Triangles,"Non-triangle source topology unsupported");using(var indices=new NativeArray<int>(desc.indexCount,Allocator.Temp)){data.GetIndices(indices,sub);copy.SetTriangles(indices.ToArray(),sub,false);}}
   }
   copy.RecalculateBounds();return copy;
  }
  static void MatchOriginalCollision(Mesh source,List<Mesh> references) {
   var points=source.vertices;float tol=Math.Max(source.bounds.size.magnitude*1e-5f,1e-7f);var uv0=new List<Vector2>();var uv1=new List<Vector2>();source.GetUVs(0,uv0);source.GetUVs(1,uv1);
   Require(uv0.Count==points.Length&&uv1.Count==points.Length,"Original source UV0/UV1 missing; explicit unsupported source");
   var grid=new Dictionary<string,List<int>>();for(int i=0;i<points.Length;i++){string k=Cell(points[i],tol);if(!grid.TryGetValue(k,out var list))grid[k]=list=new List<int>();list.Add(i);}
   var used=new bool[points.Length];long triangles=0;
   foreach(var reference in references) {
    triangles+=reference.triangles.Length/3;var a=new List<Vector2>();var b=new List<Vector2>();reference.GetUVs(0,a);reference.GetUVs(1,b);var vertices=reference.vertices;
    Require(a.Count==vertices.Length&&b.Count==vertices.Length,"Reference collision UV inventory mismatch");
    for(int i=0;i<vertices.Length;i++) {
     bool found=false;
     for(int x=-1;x<=1;x++)for(int y=-1;y<=1;y++)for(int z=-1;z<=1;z++)if(grid.TryGetValue(Cell(vertices[i],tol,x,y,z),out var indices))foreach(int j in indices) {
      if((vertices[i]-points[j]).sqrMagnitude<=tol*tol&&(a[i]-uv0[j]).sqrMagnitude<=1e-6f&&(b[i]-uv1[j]).sqrMagnitude<=1e-6f&&Mathf.Floor(b[i].y)==Mathf.Floor(uv1[j].y)){found=true;used[j]=true;}
     }
     Require(found,"Original collision does not map to Unity source geometry/UV/pages; calibrate sourceToUnity, never guess axes/scale");
    }
   }
   Require(used.All(v=>v)&&triangles==source.triangles.Length/3,"Full original source coverage missing or duplicated");
  }
  static string AssetPath(Entry e,int part) { return Generated+"/Meshes/"+e.id+"/part-"+part.ToString("D4")+".asset"; }
  static void Validate() {
   var exports=new List<string>();var ids=new HashSet<string>();
   foreach(var e in Config.entries) {
    Budget();Require(ids.Add(e.id),"Duplicate entry");Mesh source=Source(e);var index=JsonUtility.FromJson<MeshIndex>(File.ReadAllText(Path.Combine(Root,"meshes",e.id,"mesh-index.json")));
    Require(index.schema==1&&index.id==e.id&&index.parts.Length>0&&index.collision.Length>0,"Mesh index incomplete");
    int sourceChannels=Enumerable.Range(0,8).Count(j=>source.HasVertexAttribute((VertexAttribute)((int)VertexAttribute.TexCoord0+j)));Require(sourceChannels>=2&&index.parts.Concat(index.collision).All(p=>p.uvNames.Length==sourceChannels),"Original UV channel inventory was lost or changed");
    var collision=index.collision.Select(p=>Read(e,p)).ToList();var readable=ReadableSource(source);try{MatchOriginalCollision(readable,collision);}finally{UnityEngine.Object.DestroyImmediate(readable);foreach(var m in collision)UnityEngine.Object.DestroyImmediate(m);}
    for(int i=0;i<index.parts.Length;i++) {
     var mesh=Read(e,index.parts[i]);float tol=Math.Max(source.bounds.size.magnitude*.003f,1e-7f);Bounds envelope=source.bounds;envelope.Expand(tol*2);
     Require(envelope.Contains(mesh.bounds.min)&&envelope.Contains(mesh.bounds.max),"Candidate outside original source envelope");
     string path=AssetPath(e,i);Directory.CreateDirectory(Path.GetDirectoryName(path));Require(!File.Exists(path),"Refuse to overwrite generated candidate asset");AssetDatabase.CreateAsset(mesh,path);exports.Add(path);
    }
    foreach(string path in e.materialPaths)Require(AssetDatabase.LoadAssetAtPath<Material>(path)!=null,"Exact source/additional material binding missing: "+path);
    File.Copy(Path.Combine(Root,"meshes",e.id,"mesh-index.json"),Path.Combine(Output,e.id+"-mesh-index.json"));Passed.Add(e.id);
   }
   AssetDatabase.SaveAssets();AssetDatabase.ExportPackage(exports.ToArray(),Path.Combine(Output,"validated-meshes.unitypackage"),ExportPackageOptions.Default);
  }
  static void ImportPackages() {
   string directory=Arg("-mysimPackages")??throw new InvalidOperationException("Verified packages path required");
   string[] packages=Directory.GetFiles(directory,"*.unitypackage",SearchOption.AllDirectories);Require(packages.Length>0,"No verified packages");
   foreach(string file in packages){Budget();AssetDatabase.ImportPackage(file,false);}AssetDatabase.Refresh();
  }
  static string CollisionState(GameObject root) {
   return string.Join("\n",root.GetComponentsInChildren<Collider>(true).Select(c=>c.GetType().FullName+"|"+c.transform.localToWorldMatrix+"|"+EditorJsonUtility.ToJson(c)).OrderBy(x=>x));
  }
  static HashSet<string> SourceObjectIds(GameObject root) {
   var result=new HashSet<string>();foreach(var t in root.GetComponentsInChildren<Transform>(true)){result.Add(Key(t.gameObject));foreach(var c in t.GetComponents<Component>()){Require(c!=null,"Missing script in source prefab");result.Add(Key(c));}}return result;
  }
  static void Assemble(string trackId) {
   ImportPackages();Track track=Config.tracks.Single(t=>t.id==trackId);Require(Hash(Full(track.sourcePrefab))==track.sourcePrefabSha256,"Source track prefab hash mismatch");
   var original=AssetDatabase.LoadAssetAtPath<GameObject>(track.sourcePrefab);Require(original!=null,"Source track missing");var ids=SourceObjectIds(original);var root=PrefabUtility.LoadPrefabContents(track.sourcePrefab);
   var export=new List<string>{track.sourcePrefab};string before=CollisionState(root);
   try {
    var groups=root.GetComponentsInChildren<LODGroup>(true);var mappings=new Dictionary<Renderer,Renderer[]>();var matched=new HashSet<string>();
    foreach(var e in Config.entries.Where(e=>e.trackIds.Contains(trackId))) {
     Budget();Mesh source=Source(e);string indexPath=Directory.GetFiles(Arg("-mysimPackages"),e.id+"-mesh-index.json",SearchOption.AllDirectories).Single();var index=JsonUtility.FromJson<MeshIndex>(File.ReadAllText(indexPath));
     var filters=root.GetComponentsInChildren<MeshFilter>(true).Where(f=>f.sharedMesh==source).ToArray();Require(filters.Length>0,"Source mesh not present in specified track: "+e.id);
     Require(!root.GetComponentsInChildren<SkinnedMeshRenderer>(true).Any(s=>s.sharedMesh==source),"Skinned source requires dedicated rig-preserving pipeline");
     foreach(var filter in filters) {
      var old=filter.GetComponent<MeshRenderer>();Require(old!=null,"Source MeshFilter has no renderer");var materials=e.materialPaths.Select(p=>AssetDatabase.LoadAssetAtPath<Material>(p)).ToArray();Require(materials.All(m=>m!=null),"Material missing");
      var prior=old.sharedMaterials;Require(prior.Length<=materials.Length&&prior.Select((m,i)=>m==materials[i]).All(v=>v),"Original renderer material identity/order changed");
      bool inGroup=groups.Any(g=>g.GetLODs().Any(l=>l.renderers.Contains(old)));int levels=inGroup?1:e.lodHeights.Length;var renderers=new List<Renderer>[levels];for(int l=0;l<levels;l++)renderers[l]=new List<Renderer>();
      var container=new GameObject("MySimCandidate_"+e.id);container.transform.SetParent(filter.transform,false);
      for(int i=0;i<index.parts.Length;i++) {
       var part=index.parts[i];if(part.lod>=levels)continue;string asset=AssetPath(e,i);Mesh mesh=AssetDatabase.LoadAssetAtPath<Mesh>(asset);Require(mesh!=null,"Validated part asset missing");if(!export.Contains(asset))export.Add(asset);
       var child=new GameObject("part_"+i);child.layer=old.gameObject.layer;child.transform.SetParent(container.transform,false);GameObjectUtility.SetStaticEditorFlags(child,GameObjectUtility.GetStaticEditorFlags(old.gameObject));child.AddComponent<MeshFilter>().sharedMesh=mesh;
       var renderer=child.AddComponent<MeshRenderer>();renderer.sharedMaterials=materials;renderer.shadowCastingMode=old.shadowCastingMode;renderer.receiveShadows=old.receiveShadows;renderer.lightmapIndex=old.lightmapIndex;renderer.lightmapScaleOffset=old.lightmapScaleOffset;renderer.realtimeLightmapIndex=old.realtimeLightmapIndex;renderer.realtimeLightmapScaleOffset=old.realtimeLightmapScaleOffset;renderer.lightProbeUsage=old.lightProbeUsage;renderer.reflectionProbeUsage=old.reflectionProbeUsage;renderer.probeAnchor=old.probeAnchor;renderer.enabled=old.enabled;
       var block=new MaterialPropertyBlock();old.GetPropertyBlock(block);renderer.SetPropertyBlock(block);renderers[part.lod].Add(renderer);
      }
      Require(renderers.All(v=>v.Count>0),"Incomplete candidate LOD renderers");mappings.Add(old,renderers[0].ToArray());old.enabled=false;
      if(!inGroup){var group=container.AddComponent<LODGroup>();group.SetLODs(renderers.Select((v,l)=>new LOD(e.lodHeights[l],v.ToArray())).ToArray());group.RecalculateBounds();}
     }
     matched.Add(e.id);Passed.Add(e.id);
    }
    foreach(var group in groups){var lods=group.GetLODs();for(int i=0;i<lods.Length;i++)lods[i].renderers=lods[i].renderers.SelectMany(v=>v!=null&&mappings.TryGetValue(v,out var replacement)?replacement:new[]{v}).ToArray();group.SetLODs(lods);}
    Require(matched.Count>0&&CollisionState(root)==before,"Original collision or transform changed");PrefabUtility.SaveAsPrefabAsset(root,track.sourcePrefab);
   } finally { PrefabUtility.UnloadPrefabContents(root); }
   AssetDatabase.SaveAssets();AssetDatabase.ImportAsset(track.sourcePrefab,ImportAssetOptions.ForceUpdate);
   var after=AssetDatabase.LoadAssetAtPath<GameObject>(track.sourcePrefab);Require(ids.IsSubsetOf(SourceObjectIds(after)),"Original prefab GUID/fileIDs were not retained");
   AssetDatabase.ExportPackage(export.ToArray(),Path.Combine(Output,"track-"+trackId+".unitypackage"),ExportPackageOptions.Default);
  }
  static void Build() {
   ImportPackages();Require(Config.buildScenes!=null&&Config.buildScenes.Length>0,"Explicit build scenes required");foreach(string scene in Config.buildScenes)Require(File.Exists(Full(scene)),"Build scene missing");
   string executable=Path.Combine(Output,"player","MySim.x86_64");Directory.CreateDirectory(Path.GetDirectoryName(executable));
   var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=Config.buildScenes,locationPathName=executable,target=BuildTarget.StandaloneLinux64,options=BuildOptions.StrictMode});
   Require(report.summary.result==BuildResult.Succeeded,"Final Unity player build failed");
   File.WriteAllText(Path.Combine(Output,"build-summary.txt"),"Bytes="+report.summary.totalSize+" Errors="+report.summary.totalErrors+" Duration="+report.summary.totalTime);
  }
 }
}
