import sys
v=[]
for l in open(sys.argv[1]):
    p=l.split(' ',1)
    if len(p)<2 or not p[1].startswith('P,'): continue
    f=p[1].strip().split(',')
    if len(f)>=11 and f[7]=='1' and f[8]!='na': v.append(int(f[8]))
m=sum(v)/len(v); print(len(v),'mean raw',m,'Hz',m*26e6/2**14)
