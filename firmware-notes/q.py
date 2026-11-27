import sys,struct,pickle; sys.path.insert(0,'.')
import oasis as O
lit2sites,site2lit=pickle.load(open('xref.pkl','rb'))
f=O.f
def str_vaddrs(s):
    bs=s.encode(); out=[]; i=0
    while True:
        j=f.find(bs,i)
        if j<0: break
        # must be in DROM file region: fileoff 0x20..0x5431c -> vaddr
        if 0x20<=j<0x5431c:
            out.append(0x3c150020+(j-0x20))
        out.append(('raw',j))
        i=j+1
    return out
def find_func_start(pc):
    # scan back for 'entry' instr (byte 0x36, op0=6) with plausible frame
    for back in range(0,4000,1):
        a=pc-back
        b=O.read(a,3)
        if b and (b[0]==0x36) and (b[0]&0xf)==0x6:
            # entry: b0=0x36, s in b1 low nibble? check it's aN with imm
            try:
                ins=next(O.md.disasm(b,a))
                if ins.mnemonic=='entry': return a
            except: pass
    return None
def dis(pc,n=60,back=0):
    start=pc-back
    code=O.read(start,n*3)
    md=O.md; md.skipdata=True
    cnt=0
    for ins in md.disasm(code,start):
        tag=''
        if ins.mnemonic=='l32r' and ins.address in site2lit:
            reg,la,val=site2lit[ins.address]
            s=O.cstr(val,60)
            tag='  ; =0x%08x %s'%(val, ('"%s"'%s) if s and s.isprintable() else O.seg_name(val))
        mark='>>' if ins.address==pc else '  '
        print("%s0x%08x %-9s %s%s"%(mark,ins.address,ins.mnemonic,ins.op_str,tag))
        cnt+=1
        if cnt>=n: break
if __name__=='__main__':
    import sys
    s=sys.argv[1]
    print("=== string:",repr(s))
    for v in str_vaddrs(s):
        if isinstance(v,tuple): continue
        sites=lit2sites.get(v,[])
        print("vaddr 0x%08x  l32r-sites:"%v,[hex(x) for x in sites])
