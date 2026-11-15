#!/usr/bin/env python3
"""Fetch the arXiv sources of the relative-threshold siblings (siblings_rel.json) and build their full_paper.tex
with build_ablation_inputs.py, the same input format the target papers' RQ recovery uses.
Store: benchmark_sci_research/siblings_store/<arxiv_id>/ (paper.pdf, source.tar.gz, source/paper.tex, ablation_inputs/).
A sibling already downloaded as an influential reference is linked from influential_refs_store instead of fetched again.
  python3 fetch_siblings.py [-w 4]"""
import argparse, glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_refs as FR
import fix_roots
from common import target_papers, BASE, jdump
sys.path.insert(0, BASE)
import build_ablation_inputs as BAI

REF_STORE = FR.STORE
SIB = os.path.join(BASE, "siblings_store")
FR.STORE = SIB                                   # fetch_refs.work / folder() write here


def one(aid, info):
    d = FR.folder(aid)
    ref = os.path.join(REF_STORE, aid.replace("/", "_"))
    if not os.path.exists(d) and os.path.isfile(os.path.join(ref, "source", "paper.tex")):
        os.symlink(os.path.relpath(ref, SIB), d)
    m = json.load(open(os.path.join(d, "meta.json"))) if os.path.exists(os.path.join(d, "meta.json")) else {}
    if m.get("status") != "ok":
        FR.work(aid, info)
        m = json.load(open(os.path.join(d, "meta.json")))
        c = m.get("consolidate") or {}
        if m.get("status") == "ok" and str(c.get("note", "")).startswith("multiple roots"):
            fix_roots.run(d)
            m = json.load(open(os.path.join(d, "meta.json")))
    tex = Path(d) / "source" / "paper.tex"
    if m.get("status") == "ok" and tex.is_file() and not (Path(d) / "ablation_inputs" / "full_paper.tex").exists():
        BAI.process(tex)
    ok = (Path(d) / "ablation_inputs" / "full_paper.tex").exists()
    return aid, m.get("status"), ok


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("-w", type=int, default=4); a = ap.parse_args()
    os.makedirs(SIB, exist_ok=True)
    want = {}
    for coll, pid, d in target_papers():
        p = os.path.join(d, "influential_refs", "siblings_rel.json")
        if not os.path.exists(p):
            continue
        for x in json.load(open(p))["siblings"]:
            if x.get("arxiv_id"):
                want.setdefault(x["arxiv_id"], {"title": x.get("title"), "targets": []})["targets"].append(f"{coll}/{pid}")
    print(len(want), "unique arXiv siblings", flush=True)
    res = {}
    with ThreadPoolExecutor(a.w) as ex:
        fs = {ex.submit(one, k, v): k for k, v in want.items()}
        for i, f in enumerate(as_completed(fs), 1):
            try:
                aid, st, ok = f.result(); res[aid] = {"status": st, "full_paper": ok}
            except Exception as e:
                res[fs[f]] = {"status": "error", "error": repr(e)[:200], "full_paper": False}
            if i % 100 == 0:
                print(i, "/", len(fs), flush=True)
    jdump(res, os.path.join(SIB, "fetch_summary.json"))
    from collections import Counter
    print("status", Counter(v["status"] for v in res.values()), "| full_paper.tex", sum(v["full_paper"] for v in res.values()), flush=True)


if __name__ == "__main__":
    main()
