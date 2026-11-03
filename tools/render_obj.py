# Minimal numpy software rasterizer: textured, z-buffered, lambert + rim. Renders several views into one PNG.
import sys, math
import numpy as np
from PIL import Image

def load_obj(path):
    V=[];T=[];F=[]
    for line in open(path):
        if line.startswith('v '): V.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('vt '): T.append([float(x) for x in line.split()[1:3]])
        elif line.startswith('f '):
            parts=line.split()[1:]
            idx=[]
            for p in parts:
                s=p.split('/')
                vi=int(s[0])-1; ti=int(s[1])-1 if len(s)>1 and s[1] else vi
                idx.append((vi,ti))
            for k in range(1,len(idx)-1):
                F.append([idx[0],idx[k],idx[k+1]])
    return np.array(V),np.array(T) if T else None,F

def render(V,T,F,tex,yaw,size=512,pitch=0.0):
    W=H=size
    cy,sy=math.cos(yaw),math.sin(yaw)
    R=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
    cp,spp=math.cos(pitch),math.sin(pitch)
    P=np.array([[1,0,0],[0,cp,-spp],[0,spp,cp]])
    center=(V.max(0)+V.min(0))/2
    Vc=(V-center)@R.T@P.T
    scale=0.9*size/ (V.max(0)-V.min(0)).max()
    X=Vc[:,0]*scale+W/2; Y=-Vc[:,1]*scale+H/2; Z=Vc[:,2]
    img=np.zeros((H,W,3),np.float32); img[:]=(0.18,0.18,0.22)
    zb=np.full((H,W),-1e9,np.float32)
    th,tw=tex.shape[:2]
    light=np.array([0.4,0.6,0.7]); light/=np.linalg.norm(light)
    for tri in F:
        vi=[a for a,b in tri]; ti=[b for a,b in tri]
        x=X[vi];y=Y[vi];z=Z[vi]
        # facing & normal (camera looks along -z toward +z? we keep nearest = larger z)
        e1=Vc[vi[1]]-Vc[vi[0]]; e2=Vc[vi[2]]-Vc[vi[0]]
        n=np.cross(e1,e2); nl=np.linalg.norm(n)
        if nl==0: continue
        n/=nl
        x0,x1=int(max(0,math.floor(x.min()))),int(min(W-1,math.ceil(x.max())))
        y0,y1=int(max(0,math.floor(y.min()))),int(min(H-1,math.ceil(y.max())))
        if x1<x0 or y1<y0: continue
        xs,ys=np.meshgrid(np.arange(x0,x1+1)+0.5,np.arange(y0,y1+1)+0.5)
        d=(y[1]-y[2])*(x[0]-x[2])+(x[2]-x[1])*(y[0]-y[2])
        if abs(d)<1e-9: continue
        w0=((y[1]-y[2])*(xs-x[2])+(x[2]-x[1])*(ys-y[2]))/d
        w1=((y[2]-y[0])*(xs-x[2])+(x[0]-x[2])*(ys-y[2]))/d
        w2=1-w0-w1
        m=(w0>=-1e-4)&(w1>=-1e-4)&(w2>=-1e-4)
        if not m.any(): continue
        zz=w0*z[0]+w1*z[1]+w2*z[2]
        sub=zb[y0:y1+1,x0:x1+1]
        m&=zz>sub
        if not m.any(): continue
        if T is not None:
            uv=T[ti]
            u=w0*uv[0,0]+w1*uv[1,0]+w2*uv[2,0]; v=w0*uv[0,1]+w1*uv[1,1]+w2*uv[2,1]
            tx=np.clip((u%1.0)*tw,0,tw-1).astype(int); ty=np.clip((1-(v%1.0))*th,0,th-1).astype(int)
            col=tex[ty,tx,:3]
        else:
            col=np.ones(xs.shape+(3,))*0.8
        shade=0.55+0.45*abs(float(n@light))
        sub[m]=zz[m]
        img[y0:y1+1,x0:x1+1][m]=col[m]*shade
    return (np.clip(img,0,1)*255).astype(np.uint8)

if __name__=='__main__':
    obj,texp,out=sys.argv[1],sys.argv[2],sys.argv[3]
    size=int(sys.argv[4]) if len(sys.argv)>4 else 480
    V,T,F=load_obj(obj)
    tex=np.asarray(Image.open(texp).convert('RGB'),np.float32)/255.0 if texp!='-' else None
    if tex is None: tex=np.ones((4,4,3),np.float32)
    views=[0, math.pi/2, math.pi, -math.pi/4]
    ims=[render(V,T,F,tex,a,size) for a in views]
    Image.fromarray(np.concatenate(ims,1)).save(out)
    print('verts',len(V),'tris',len(F),'bbox',V.min(0),V.max(0))
