"""Lossless float32 UV exchange; deliberately no normalization, welding or FBX import."""
import io,math,struct
MAGIC=b'MYSMESH1'
MAX_VERTICES=3_000_000
def write_mesh(path,vertices,submeshes,uv_count,tangents=False,colors=False):
 if not 0<=uv_count<=8 or not 0<len(vertices)<=MAX_VERTICES:raise ValueError('Mesh inventory budget')
 stride=6+uv_count*2+(4 if tangents else 0)+(4 if colors else 0)
 with open(path,'wb') as f:
  f.write(MAGIC);f.write(struct.pack('<5I',len(vertices),uv_count,len(submeshes),int(tangents),int(colors)))
  for row in vertices:
   if len(row)!=stride or not all(math.isfinite(x) for x in row):raise ValueError('Nonfinite or wrong vertex stride')
   f.write(struct.pack('<'+'f'*stride,*row))
  for indices in submeshes:
   if len(indices)%3 or any(i<0 or i>=len(vertices) for i in indices):raise ValueError('Invalid triangle index')
   f.write(struct.pack('<I',len(indices)));f.write(struct.pack('<'+'I'*len(indices),*indices))
def read_mesh(path):
 with open(path,'rb') as f:
  if f.read(8)!=MAGIC:raise ValueError('Wrong mesh magic')
  count,uvs,subs,tangents,colors=struct.unpack('<5I',f.read(20))
  if not 0<count<=MAX_VERTICES or uvs>8 or not 0<subs<=128 or tangents>1 or colors>1:raise ValueError('Invalid mesh header')
  stride=6+uvs*2+tangents*4+colors*4;fmt='<'+('f'*stride);rows=[]
  for _ in range(count):
   row=struct.unpack(fmt,f.read(stride*4))
   if not all(math.isfinite(x) for x in row):raise ValueError('Nonfinite mesh data')
   rows.append(row)
  triangles=[]
  for _ in range(subs):
   n,=struct.unpack('<I',f.read(4))
   if n%3 or n>count*12:raise ValueError('Triangle budget')
   values=struct.unpack('<'+'I'*n,f.read(n*4))
   if any(i>=count for i in values):raise ValueError('Bad index')
   triangles.append(values)
  if f.read(1):raise ValueError('Trailing mesh data')
 return dict(vertices=rows,submeshes=triangles,uv_count=uvs)
