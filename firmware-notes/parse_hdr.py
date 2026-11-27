import struct, sys
f=open('/home/bill/dev/WillyGarage/oasis/backup/app0.bin','rb').read()
# ESP image header: magic(1)=0xE9, seg_count(1), spi_mode(1), spi_speed/size(1), entry(4)
magic,segc,spim,spis=f[0],f[1],f[2],f[3]
entry=struct.unpack('<I',f[4:8])[0]
print("magic %02x segcount %d entry 0x%08x"%(magic,segc,entry))
# extended header 16 bytes after first 8? For esp-idf: after 8-byte header comes 16-byte extended header? Actually: 8 byte header, then segments. But esp32 has extended header of 16 bytes WLH... 
# Standard: struct esp_image_header_t is 24 bytes (8 + wp_pin + spi_pin_drv(3) + chip_id(2)+ ... + hash_appended)
# Let's follow esp-idf: header is 24 bytes.
off=24
APP_LOAD=off
segs=[]
for i in range(segc):
    load,length=struct.unpack('<II',f[off:off+8]); off+=8
    data_off=off
    segs.append((load,length,data_off))
    off+=length
    print("seg %d load 0x%08x len 0x%06x fileoff 0x%06x"%(i,load,length,data_off))
print("end off 0x%x filelen 0x%x"%(off,len(f)))
import pickle
pickle.dump((segs,entry),open('segs.pkl','wb'))
