#!/usr/bin/env python3
"""Step 5b: re-pick the root file for references whose source has several \\documentclass files
(rebuttals, templates, example.tex, backups, workshop versions ...).
  1. arXiv's 00README(.json|.yaml) 'toplevel' file, when present, is authoritative;
  2. otherwise every candidate is consolidated and the one whose paper.tex covers the most of the
     PDF's vocabulary (words >= 6 letters) wins.
meta.json gets root_choice = {method, candidates: {file: coverage}}.
"""
import glob, json, os, re, subprocess, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consolidate_v2 as cv
from fetch_refs import STORE
from common import jdump

WORD = re.compile(r'[A-Za-z]{6,}')


def coverage(pdf_words, tex):
    tw = set(w.lower() for w in WORD.findall(tex))
    return round(len(pdf_words & tw) / max(1, len(pdf_words)), 3)


def readme_toplevel(src):
    for p in glob.glob(os.path.join(src, '00README*')):
        t = open(p, errors='replace').read()
        try:
            j = json.loads(t)
            for s in j.get('sources', []):
                if s.get('usage') == 'toplevel':
                    return s['filename']
        except Exception:
            m = re.search(r'filename:\s*"?([^"\n]+\.tex)"?\s*\n\s*usage:\s*toplevel', t) or \
                re.search(r'usage:\s*toplevel\s*\n\s*filename:\s*"?([^"\n]+\.tex)', t)
            if m:
                return m.group(1).strip()
    return None


def run(d):
    mp = os.path.join(d, 'meta.json')
    m = json.load(open(mp))
    c = m.get('consolidate') or {}
    if m.get('status') != 'ok' or not str(c.get('note', '')).startswith('multiple roots'):
        return None
    src, aid = os.path.join(d, 'source'), os.path.basename(d)
    cands = [x.strip() for x in c['note'].split(':', 1)[1].split(',')]
    pdf = subprocess.run(['pdftotext', os.path.join(d, 'paper.pdf'), '-'], capture_output=True, timeout=180).stdout.decode('utf-8', 'replace') if os.path.isfile(os.path.join(d, 'paper.pdf')) else ''   # no PDFs fetched: same as empty pdftotext
    pw = set(w.lower() for w in WORD.findall(pdf))
    top = readme_toplevel(src)
    scores, best = {}, None
    if top and os.path.isfile(os.path.join(src, top)):
        method, best = '00README toplevel', top
    else:
        method = 'best PDF coverage'
        for cand in cands:
            cv.OVERRIDES[aid] = cand
            r = cv.process(src)
            scores[cand] = coverage(pw, open(os.path.join(src, 'paper.tex'), errors='replace').read()) if r['status'] == 'ok' else 0
        best = max(scores, key=scores.get) if len(pw) > 50 else c['root']
    cv.OVERRIDES[aid] = best
    r = cv.process(src)
    r['note'] = c['note']
    m['consolidate'] = r
    m['root_choice'] = {'method': method, 'previous_root': c['root'], 'root': best, 'candidates': scores}
    jdump(m, mp)
    return aid, c['root'], best, method


if __name__ == '__main__':
    ds = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(STORE, '*', 'meta.json')))
    with Pool(24) as pool:
        res = [r for r in pool.map(run, ds, chunksize=4) if r]
    changed = [r for r in res if r[1] != r[2]]
    print(len(res), 'multi-root references;', len(changed), 'root changed')
    for r in changed:
        print(*r)
