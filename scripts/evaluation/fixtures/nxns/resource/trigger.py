#!/usr/bin/env python3
import json, socket, struct, sys, time

def q(name):
    labels = name.rstrip('.').split('.')
    return struct.pack('!HHHHHH',0x4e58,0x0100,1,0,0,0)+b''.join(bytes([len(x)])+x.encode() for x in labels)+b'\0\0\1\0\1'

def ask(host, name, timeout=8):
    raw=q(name); started=time.perf_counter(); m={'server':host,'name':name,'query_bytes':len(raw),'timeout':False,'rcode':None,'answer_count':None,'authority_count':None,'additional_count':None}
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.settimeout(timeout); s.sendto(raw,(host,53)); data,_=s.recvfrom(65535)
        if len(data)<12: raise ValueError('short DNS response')
        _id,flags,_qd,an,ns,ar=struct.unpack('!HHHHHH',data[:12]); m.update({'response_bytes':len(data),'rcode':flags&15,'answer_count':an,'authority_count':ns,'additional_count':ar})
    except socket.timeout: m.update({'timeout':True,'response_bytes':0})
    except Exception as exc: m['error']=f'{type(exc).__name__}: {exc}'
    m['latency_ms']=round((time.perf_counter()-started)*1000,3); return m

def main():
    auth=ask('auth','x.example.com'); resolver=ask('resolver','x.example.com',12)
    out={'attack':'NXNS','authoritative':auth,'resolver':resolver}
    print(json.dumps(out,sort_keys=True),flush=True)
    ok=auth.get('authority_count',0)>=50 and (resolver.get('timeout') or resolver.get('rcode') not in (None,0))
    return 0 if ok else 1

if __name__=='__main__': sys.exit(main())
