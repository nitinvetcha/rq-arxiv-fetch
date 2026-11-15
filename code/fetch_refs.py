#!/usr/bin/env python3
"""Step 4: download every unique influential reference that has an arXiv id and consolidate its LaTeX.

Shared store (each reference once, however many target papers cite it):
  benchmark_sci_research/influential_refs_store/<arxiv_id>/   ('/' in old-style ids becomes '_')
      paper.pdf, source.tar.gz, source/ (text files only: tex/bbl/bib/sty/cls/listings),
      source/paper.tex (consolidated, same consolidate_v2.py as the target papers), title.txt, meta.json
Per target paper: papers/<id>/influential_refs/papers/<arxiv_id> -> symlink into the store.
usage: fetch_refs.py [-w WORKERS]
"""
import argparse, gzip, io, json, os, re, shutil, sys, tarfile, time, glob
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import target_papers, BASE, jdump, UA
import consolidate_v2

STORE = os.path.join(BASE, 'influential_refs_store')
BIN_EXT = re.compile(r'\.(png|jpe?g|gif|bmp|tiff?|pdf|eps|ps|svg|mp4|mov|avi|gif|zip|gz|tgz|tar|xz|bz2|7z|npy|npz|pkl|pt|pth|ckpt|h5|mat|wav|mp3|ttf|otf|pfb|woff2?|psd|ai|fig|xcf|webp|ico|doc|docx|pptx?|xlsx?|bin|exe|so|o|dvi|synctex|pdf_tex)$', re.I)
MAX_MEMBER = 8 << 20


def folder(aid):
    return os.path.join(STORE, aid.replace('/', '_'))


def get(url, dest, tries=6):
    for i in range(tries):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=(20, 120)) as r:
                if r.status_code == 404:
                    return False
                if r.status_code in (403, 429, 503):
                    time.sleep(int(r.headers.get('Retry-After', 10 * (i + 1))))
                    continue
                r.raise_for_status()
                exp = int(r.headers.get('Content-Length', -1))
                n = 0
                with open(dest + '.part', 'wb') as f:
                    for c in r.iter_content(1 << 16):
                        f.write(c)
                        n += len(c)
                if exp >= 0 and n != exp:
                    raise IOError('truncated')
                os.replace(dest + '.part', dest)
                return True
        except Exception:
            time.sleep(3 * (i + 1))
    raise RuntimeError('failed ' + url)


def extract_text(tgz, out):
    """extract only text-like members; returns 'tar' | 'single' | 'pdf_only' | 'bad'."""
    os.makedirs(out, exist_ok=True)
    with open(tgz, 'rb') as f:
        head = f.read(8)
    if head.startswith(b'%PDF'):
        return 'pdf_only'
    try:
        with tarfile.open(tgz) as t:
            mem = [m for m in t.getmembers() if m.isfile() and m.size <= MAX_MEMBER and not BIN_EXT.search(m.name)]
            t.extractall(out, members=mem, filter='data')
        return 'tar'
    except tarfile.ReadError:
        pass
    try:
        with gzip.open(tgz) as g:
            data = g.read()
    except OSError:
        data = head + open(tgz, 'rb').read()[8:]   # uncompressed single file
    if data.startswith(b'%PDF'):
        return 'pdf_only'
    if b'\\documentclass' in data or b'\\begin{document}' in data or b'\\input' in data:
        with open(os.path.join(out, 'main.tex'), 'wb') as f:
            f.write(data)
        return 'single'
    return 'bad'


def work(aid, info):
    if shutil.disk_usage(BASE).free < (30 << 30):
        raise RuntimeError('disk guard: less than 30 GB free, not downloading')
    d = folder(aid)
    meta_p = os.path.join(d, 'meta.json')
    if os.path.exists(meta_p):
        m = json.load(open(meta_p))
        if m.get('status') in ('ok', 'ok_pdf_text', 'pdf_only', 'no_tex', 'no_root', 'bad_source', 'not_found'):
            return aid, 'skip ' + m['status']
    os.makedirs(d, exist_ok=True)
    pdf, src_tgz, src = os.path.join(d, 'paper.pdf'), os.path.join(d, 'source.tar.gz'), os.path.join(d, 'source')
    got_pdf = os.path.exists(pdf) or get('https://export.arxiv.org/pdf/%s' % aid, pdf)
    got_src = os.path.exists(src_tgz) or get('https://export.arxiv.org/e-print/%s' % aid, src_tgz)
    meta = {'arxiv_id': aid, 'title': info['title'], 'cited_by_targets': info['targets'], 'pdf': bool(got_pdf)}
    if not got_src:
        meta['status'] = 'not_found' if not got_pdf else 'pdf_only'
    else:
        if os.path.isdir(src):
            shutil.rmtree(src)
        kind = extract_text(src_tgz, src)
        meta['source_kind'] = kind
        if kind == 'pdf_only':
            os.replace(src_tgz, pdf if not got_pdf else src_tgz + '.pdf')
            meta['status'] = 'pdf_only'
        elif kind == 'bad':
            meta['status'] = 'bad_source'
        else:
            own = os.path.join(src, 'paper.tex')
            if os.path.isfile(own):            # keep the author's own paper.tex, as for the target papers
                os.replace(own, own + '.orig.bak')
            try:
                r = consolidate_v2.process(src)
            except Exception as e:
                r = {'status': 'error', 'error': repr(e)}
            meta['consolidate'] = r
            meta['status'] = r['status']
    with open(os.path.join(d, 'title.txt'), 'w') as f:
        f.write(info['title'] or '')
    jdump(meta, meta_p)
    return aid, meta['status']


def collect():
    refs = {}
    for coll, pid, d in target_papers():
        p = os.path.join(d, 'influential_refs', 'influential.json')
        if not os.path.exists(p):
            continue
        for e in json.load(open(p))['influential']:
            a = e.get('arxiv_id')
            if not a or a == pid:
                continue
            r = refs.setdefault(a, {'title': e.get('title'), 'targets': []})
            r['targets'].append('%s/%s' % (coll, pid))
    return refs


def link_all():
    for coll, pid, d in target_papers():
        p = os.path.join(d, 'influential_refs', 'influential.json')
        if not os.path.exists(p):
            continue
        ld = os.path.join(d, 'influential_refs', 'papers')
        if os.path.isdir(ld):
            shutil.rmtree(ld)
        os.makedirs(ld)
        for e in json.load(open(p))['influential']:
            a = e.get('arxiv_id')
            if a and os.path.isfile(os.path.join(folder(a), 'source', 'paper.tex')):
                ln = os.path.join(ld, a.replace('/', '_'))
                if not os.path.lexists(ln):
                    os.symlink(os.path.relpath(folder(a), ld), ln)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('-w', type=int, default=4)
    ap.add_argument('--link-only', action='store_true')
    a = ap.parse_args()
    if not a.link_only:
        refs = collect()
        os.makedirs(STORE, exist_ok=True)
        print(len(refs), 'unique arXiv references', flush=True)
        with ThreadPoolExecutor(a.w) as ex:
            fs = {ex.submit(work, k, v): k for k, v in refs.items()}
            for i, f in enumerate(as_completed(fs), 1):
                try:
                    print('[%d/%d]' % (i, len(fs)), *f.result(), flush=True)
                except Exception as e:
                    print('[%d/%d] %s ERROR %r' % (i, len(fs), fs[f], e), flush=True)
    link_all()
    print('linked', flush=True)
