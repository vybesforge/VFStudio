#!/usr/bin/env python3
"""Fetch only selected entries from a remote ZIP (Godot .tpz) via HTTP range requests.
Usage: tpz_partial.py URL OUTDIR pattern [pattern...]
Entries are written to OUTDIR with the leading 'templates/' stripped."""
import sys, struct, zlib, urllib.request, re, os

url, outdir, pats = sys.argv[1], sys.argv[2], sys.argv[3:]

def get(start, end):
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}", "User-Agent": "curl/8"})
    with urllib.request.urlopen(req) as r:
        return r.read()

with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "curl/8"})) as r:
    total = int(r.headers["Content-Length"])
tail = get(max(0, total - 65536), total - 1)
i = tail.rfind(b"PK\x05\x06")
if i < 0:
    sys.exit("EOCD not found")
disk_entries, cd_size, cd_off = struct.unpack("<HII", tail[i+10:i+20])
if cd_off == 0xFFFFFFFF or disk_entries == 0xFFFF:  # zip64
    j = tail.rfind(b"PK\x06\x06")
    cd_size, cd_off = struct.unpack("<QQ", tail[j+40:j+56])
cd = get(cd_off, cd_off + cd_size - 1)
entries = []
p = 0
while p < len(cd) and cd[p:p+4] == b"PK\x01\x02":
    method, = struct.unpack("<H", cd[p+10:p+12])
    csize, usize = struct.unpack("<II", cd[p+20:p+28])
    nlen, elen, clen = struct.unpack("<HHH", cd[p+28:p+34])
    lho, = struct.unpack("<I", cd[p+42:p+46])
    name = cd[p+46:p+46+nlen].decode()
    extra = cd[p+46+nlen:p+46+nlen+elen]
    if 0xFFFFFFFF in (csize, usize, lho):  # zip64 extra
        q = 0
        while q < len(extra):
            hid, hsz = struct.unpack("<HH", extra[q:q+4])
            if hid == 1:
                vals = struct.unpack("<" + "Q" * (hsz // 8), extra[q+4:q+4+hsz])
                k = 0
                if usize == 0xFFFFFFFF: usize = vals[k]; k += 1
                if csize == 0xFFFFFFFF: csize = vals[k]; k += 1
                if lho == 0xFFFFFFFF: lho = vals[k]; k += 1
            q += 4 + hsz
    entries.append((name, method, csize, usize, lho))
    p += 46 + nlen + elen + clen
print(f"zip has {len(entries)} entries, total {total/1e6:.0f} MB")
want = [e for e in entries if any(re.search(pt, e[0]) for pt in pats)]
for name, method, csize, usize, lho in want:
    hdr = get(lho, lho + 29)
    nlen, elen = struct.unpack("<HH", hdr[26:30])
    start = lho + 30 + nlen + elen
    print(f"fetching {name} ({csize/1e6:.1f} MB compressed)", flush=True)
    data = get(start, start + csize - 1)
    if method == 8:
        data = zlib.decompress(data, -15)
    elif method != 0:
        sys.exit(f"unsupported method {method} for {name}")
    assert len(data) == usize, (name, len(data), usize)
    rel = name[len("templates/"):] if name.startswith("templates/") else name
    dest = os.path.join(outdir, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  -> {dest}")
