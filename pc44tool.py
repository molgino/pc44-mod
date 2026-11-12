#!/usr/bin/env python3
"""PC44 SysEx-Firmware: decode / encode (Faderfox PC44, Format V0100/V0101).
  decode: pc44tool.py decode in.syx out.bin
  encode: pc44tool.py encode in.bin template.syx out.syx   (Kopf/Version aus template übernehmen)
Prüfwerte (aus V0100/V0101 rekonstruiert, an allen 109 Seiten verifiziert):
  Seitenprüfwert = (sum(i * byte_i) + seitenindex) & 0xFFFF, i=0..255; 4B = High-, 4C = Lowbyte
  Kopf 0x45/0x46 = Nummer der letzten Seite (z.B. 0x006C bei 109 Seiten)
  Kopf 0x47/0x48 = 16-Bit-Prüfsumme: (sum(alle Datenbytes) + 0xFF4B) & 0xFFFF, High-Byte zuerst
"""
import sys
PAGE=256
def enc(tag,b): return bytes([tag,0x20|(b>>4),0x10|(b&15)])
def dec(r): return ((r[1]&15)<<4)|(r[2]&15)

def decode(syx):
    assert syx[0]==0xF0 and syx[-1]==0xF7
    body=syx[1:-1]; rec=[body[i:i+3] for i in range(3,len(body)-2,3)]
    hdr=[dec(r) for r in rec[:8]]
    out=bytearray(); i=8; pages=0
    while i<len(rec) and rec[i][0]==0x49:
        out+=bytes(dec(r) for r in rec[i+2:i+258]); i+=260
        while i<len(rec) and rec[i]==b'\0\0\0': i+=1
        pages+=1
    return hdr,bytes(out)

def pagecs(idx,page): return (sum(i*v for i,v in enumerate(page))+idx)&0xFFFF

def encode(img,hdr):
    assert len(img)%PAGE==0
    hdr=list(hdr)
    last=len(img)//PAGE-1                 # Kopf 0x45/0x46 = Nummer der letzten Seite (16 Bit)
    hdr[4]=last>>8; hdr[5]=last&0xFF
    cs=(sum(img)+0xFF4B)&0xFFFF           # Kopf 0x47/0x48 = 16-Bit-Prüfsumme (High, Low)
    hdr[6]=cs>>8; hdr[7]=cs&0xFF
    body=bytearray(b'\0\0\0')
    for t,v in zip(range(0x41,0x49),hdr): body+=enc(t,v)
    for k in range(len(img)//PAGE):
        pg=img[k*PAGE:(k+1)*PAGE]
        body+=enc(0x49,k>>8)+enc(0x4A,k&255)
        for v in pg: body+=enc(0x4D,v)
        c=pagecs(k,pg); body+=enc(0x4B,c>>8)+enc(0x4C,c&255)+b'\0\0\0'*20
    body+=enc(0x4F,0x08)
    return bytes([0xF0])+bytes(body)+bytes([0xF7])

USAGE='''Benutzung:
  python pc44tool.py decode  eingabe.syx  ausgabe.bin
  python pc44tool.py encode  abbild.bin   vorlage.syx  ausgabe.syx

Beispiel (Eingabeaufforderung, im Ordner des Skripts):
  python pc44tool.py decode PC44_V0101.syx image.bin
  python pc44tool.py encode image.bin PC44_V0101.syx neu.syx
'''

if __name__=='__main__':
    need={'decode':4,'encode':5}
    if len(sys.argv)<2 or sys.argv[1] not in need or len(sys.argv)!=need[sys.argv[1]]:
        print(USAGE); sys.exit(1)
    m=sys.argv[1]
    if m=='decode':
        h,img=decode(open(sys.argv[2],'rb').read()); open(sys.argv[3],'wb').write(img)
        print('Kopf',[hex(x) for x in h],len(img),'Bytes')
    elif m=='encode':
        img=open(sys.argv[2],'rb').read(); h,_=decode(open(sys.argv[3],'rb').read())
        open(sys.argv[4],'wb').write(encode(img,h))
