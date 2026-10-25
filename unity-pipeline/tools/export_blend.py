"""Run ONLY on a remote Blender CPU runner, with --disable-autoexec."""
import argparse,hashlib,json,sys,math
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).parent))
from mesh_binary import write_mesh
from intake import digest,MAX_OUTPUT

def export_object(obj,collision,outdir,label,lod,material_count):
 mesh=obj.data;mesh.calc_loop_triangles()
 if len(mesh.uv_layers)>8 or len(mesh.color_attributes)>1:raise ValueError('Unsupported channels must not be silently dropped')
 matrix=collision.matrix_world.inverted()@obj.matrix_world;linear=matrix.to_3x3();normal_matrix=linear.inverted().transposed();flip=linear.determinant()<0
 has_tangents=len(mesh.uv_layers)>0
 if has_tangents:mesh.calc_tangents(uvmap=mesh.uv_layers[0].name)
 color=mesh.color_attributes[0] if len(mesh.color_attributes) else None
 rows=[];submeshes=[[] for _ in range(material_count)];parts=[];piece=0
 def flush():
  nonlocal rows,submeshes,piece
  if not rows:return
  file=f'{label}-{piece:03d}.meshbin';path=outdir/file;write_mesh(path,rows,submeshes,len(mesh.uv_layers),has_tangents,bool(color))
  parts.append(dict(file=file,sha256=digest(path),name=obj.name,lod=lod,vertices=len(rows),triangles=sum(len(s)//3 for s in submeshes),uvNames=[u.name for u in mesh.uv_layers]));piece+=1;rows=[];submeshes=[[] for _ in range(material_count)]
 for tri in mesh.loop_triangles:
  if len(rows)+3>999_999:flush()
  mi=mesh.polygons[tri.polygon_index].material_index
  if not 0<=mi<material_count:raise ValueError('Candidate has an unmapped Unity material slot')
  indices=[]
  for loop_id in tri.loops:
   loop=mesh.loops[loop_id];position=matrix@mesh.vertices[loop.vertex_index].co;normal=(normal_matrix@mesh.corner_normals[loop_id].vector).normalized();row=list(position)+list(normal)
   for layer in mesh.uv_layers:row.extend(layer.data[loop_id].uv)
   if has_tangents:
    tangent=(linear@loop.tangent).normalized();row.extend([*tangent,loop.bitangent_sign*(-1 if flip else 1)])
   if color:
    index=loop_id if color.domain=='CORNER' else loop.vertex_index
    if color.domain not in ('CORNER','POINT'):raise ValueError('Unsupported color domain')
    row.extend(color.data[index].color)
   if not all(math.isfinite(x) for x in row):raise ValueError('Nonfinite candidate')
   indices.append(len(rows));rows.append(row)
  submeshes[mi].extend(reversed(indices) if flip else indices)
 flush();return parts

def main():
 p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);root=Path(args.workspace);manifest=json.loads((root/'shard.json').read_text())
 for entry in manifest['entries']:
  directory=root/'meshes'/entry['id'];blend=directory/'candidate.blend'
  if digest(blend)!=entry['blendSha256']:raise ValueError('Candidate changed after intake')
  wanted=[entry['collisionObject']]+[p['object'] for p in entry['parts']]
  if len(set(wanted))!=len(wanted):raise ValueError('Original collision cannot also be a render part')
  with bpy.data.libraries.load(str(blend),link=False) as (src,dst):
   missing=set(wanted)-set(src.objects)
   if missing:raise ValueError('Explicit candidate object roles absent: '+str(sorted(missing)))
   dst.objects=wanted
  objects={o.name:o for o in dst.objects}
  if set(objects)!=set(wanted) or any(o.type!='MESH' for o in objects.values()):raise ValueError('Object role mismatch')
  collision=objects[entry['collisionObject']];parts=[]
  for i,role in enumerate(entry['parts']):parts+=export_object(objects[role['object']],collision,directory,'render-'+str(i),role['lod'],len(entry['materialPaths']))
  # Collision is exchanged only to compare against Unity's original source; it never replaces driving collision.
  collision_parts=export_object(collision,collision,directory,'source-collision',-1,len(entry['materialPaths']))
  (directory/'mesh-index.json').write_text(json.dumps(dict(schema=1,id=entry['id'],parts=parts,collision=collision_parts),indent=2))
  if sum(f.stat().st_size for f in root.rglob('*.meshbin'))>MAX_OUTPUT:raise ValueError('1GiB shard output cutoff exceeded; use a smaller distinct shard')
  for obj in objects.values():
   mesh=obj.data;bpy.data.objects.remove(obj)
   if mesh.users==0:bpy.data.meshes.remove(mesh)
 print('Exported CPU exchange for',len(manifest['entries']),'unique sources; no UV normalization')
if __name__=='__main__':main()
