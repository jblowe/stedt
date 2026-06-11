#!/usr/bin/env python3
"""One-shot golden-corpus freeze of the original STEDT web app (stedtdb.johnblowe.com).

Reads MANIFEST.tsv (category, url, file, why), fetches each URL sequentially with a
polite throttle, and saves the raw response bytes verbatim — no reformatting, so the
archive stays byte-faithful for parity diffing. Progress + integrity go to FETCHLOG.tsv
(url, status, bytes, sha256, seconds). Rerunning skips files that already exist, so an
interrupted run just resumes.
"""
import csv, hashlib, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
THROTTLE = 1.2          # seconds between requests — this is someone else's small server
TIMEOUT = 120           # the original can be slow on big result sets
RETRIES = 3
UA = 'stedt-revival-archiver/1 (lukegessler@gmail.com; preserving STEDT before shutdown)'

manifest = list(csv.DictReader(open(os.path.join(ROOT, 'MANIFEST.tsv'), encoding='utf8'), delimiter='\t'))
logpath = os.path.join(ROOT, 'FETCHLOG.tsv')
have_log = os.path.exists(logpath)
log = open(logpath, 'a', encoding='utf8')
if not have_log:
    log.write('url\tstatus\tbytes\tsha256\tseconds\n')

done = skipped = failed = 0
for i, row in enumerate(manifest, 1):
    dest = os.path.join(ROOT, row['file'])
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        skipped += 1
        continue
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    body, status, err = None, 0, None
    t0 = time.time()
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(row['url'], headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body, status = resp.read(), resp.status
            break
        except Exception as e:
            err = e
            status = getattr(e, 'code', 0) or 0
            if status in (404, 500):      # real answer from the app; record it, don't hammer
                body = getattr(e, 'read', lambda: b'')() or b''
                break
            time.sleep(5 * (attempt + 1))
    secs = time.time() - t0
    if body is not None:
        with open(dest, 'wb') as f:
            f.write(body)
        sha = hashlib.sha256(body).hexdigest()
        log.write(f"{row['url']}\t{status}\t{len(body)}\t{sha}\t{secs:.2f}\n")
        done += 1
    else:
        log.write(f"{row['url']}\tFAIL:{err}\t0\t-\t{secs:.2f}\n")
        failed += 1
    log.flush()
    if i % 25 == 0:
        print(f'[{i}/{len(manifest)}] done={done} skipped={skipped} failed={failed}', flush=True)
    time.sleep(THROTTLE)

print(f'FINISHED: done={done} skipped={skipped} failed={failed} of {len(manifest)}', flush=True)
