import struct,pickle
segs,entry=pickle.load(open('segs.pkl','rb'))
f=open('/home/bill/dev/WillyGarage/oasis/backup/app0.bin','rb').read()
# Build minimal ELF32 little-endian Xtensa with PROGBITS sections per segment
EM_XTENSA=94
secs=[]
names=['.seg0_drom','.seg1_dram','.seg2_iram','.seg3_irom','.seg4_iram2']
for i,(load,length,fo) in enumerate(segs):
    secs.append((names[i],load,f[fo:fo+length]))
# shstrtab
shstr=b'\x00'
nameoff=[]
for n,_,_ in secs:
    nameoff.append(len(shstr)); shstr+=n.encode()+b'\x00'
shstr_name=len(shstr); shstr+=b'.shstrtab\x00'
# layout
ehsize=52; shentsize=40
out=bytearray()
# we'll place section data after header, then shstrtab, then section headers
data_off=ehsize
body=bytearray()
sec_hdrs=[]
cur=data_off
for i,(n,load,d) in enumerate(secs):
    off=cur
    body+=d; cur+=len(d)
    sec_hdrs.append((nameoff[i],1,6,load,off,len(d),0,0,4,0)) # PROGBITS alloc+exec
# shstrtab section
shstr_off=cur
body+=shstr; cur+=len(shstr)
# align
sh_table_off=cur
# section headers: null + secs + shstrtab
headers=[]
headers.append((0,0,0,0,0,0,0,0,0,0))
for h in sec_hdrs: headers.append(h)
headers.append((shstr_name,3,0,0,shstr_off,len(shstr),0,0,1,0)) # STRTAB
shnum=len(headers); shstrndx=shnum-1
# ELF header
e=bytearray(52)
e[0:4]=b'\x7fELF'; e[4]=1; e[5]=1; e[6]=1
struct.pack_into('<HHIIIIIHHHHHH',e,16,
    2, EM_XTENSA, 1, entry, 0, sh_table_off, 0x300,
    52, 0, 0, shentsize, shnum, shstrndx)
out+=e; out+=body
# section header table
for h in headers:
    out+=struct.pack('<10I',*h)
open('app0.elf','wb').write(out)
print('wrote app0.elf', len(out),'entry',hex(entry))
