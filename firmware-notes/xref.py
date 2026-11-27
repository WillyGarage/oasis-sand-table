import sys,struct,pickle; sys.path.insert(0,'.')
import oasis as O
f=O.f; SEG=O.SEG
# code segments to scan: IROM(seg3), IRAM(seg2,seg4)
scan_ranges=[(0x42000020,0x421402b8,0x060020),(0x40374000,0x40379fcc,0x05a04c),(0x40379fcc,0x403884b4,0x1a02c0)]
# Build l32r index: literal_value -> list of (pc, reg)
from collections import defaultdict
lit2sites=defaultdict(list)
site2lit={}
for lo,hi,fo in scan_ranges:
    data=f[fo:fo+(hi-lo)]
    for k in range(len(data)-2):
        b0=data[k]
        if (b0&0xf)!=0x1: continue
        imm16=data[k+1]|(data[k+2]<<8)
        pc=lo+k
        vaddr=((pc+3)&0xFFFFFFFC)+(imm16<<2)-0x40000
        val=O.u32(vaddr)
        if val is None: continue
        reg=(b0>>4)&0xf
        lit2sites[val].append(pc)
        site2lit[pc]=(reg,vaddr,val)
pickle.dump((dict(lit2sites),site2lit),open('xref.pkl','wb'))
print("total l32r candidate sites:",len(site2lit))
# validate with capstone on a few
md=O.md; md.skipdata=False
cnt=0
for pc,(reg,la,val) in list(site2lit.items())[:2000]:
    code=O.read(pc,3)
    try:
        ins=next(O.md.disasm(code,pc))
    except StopIteration:
        continue
    if ins.mnemonic=='l32r':
        cnt+=1
print("validated l32r (first2000):",cnt)
