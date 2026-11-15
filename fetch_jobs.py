"""Standalone arXiv LaTeX fetch for the RQB task-7 human follow-up papers whose recovered RQs are missing.
Same code path as benchmark_sci_research/task_7_seedtier/followups.py in RQB (fetch_siblings.one -> fetch_refs.work ->
consolidate_v2 -> fix_roots -> build_ablation_inputs; prompt = task_5/prompt_template.md with full_paper.tex), with the two
add3 settings used there: no PDFs, and the arxiv.org/e-print host instead of export.arxiv.org.

Input  jobs.jsonl  {rq_id, arxiv, title, gid, row, corpus_rq}   (one row per (rq_id, group); first group wins, as in followups.py)
Output out/prompts_<stamp>.jsonl.gz  rows {rq_id, arxiv, title, groups: [gid], row, corpus_rq, prompt}
       out/missing.jsonl              rows {rq_id, gid, row, arxiv, why}   (no LaTeX source etc.; "error ..." rows are retried)
       out/status.json                counters
Every --push-min minutes the open shard is closed, committed and pushed; after the push is verified (origin/main == HEAD and the
shard blob is on origin) the downloaded sources of those papers are deleted from work/ to save disk.
Resumable: rq_ids already in out/ are skipped.
  python3 fetch_jobs.py [-w 3] [--reverse] [--push-min 20] [--no-push]"""
import argparse, glob, gzip, json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("RQF_WORK", os.path.join(HERE, "work"))
sys.path.insert(0, os.path.join(HERE, "code"))
import fetch_siblings as FS
_g = FS.FR.get
FS.FR.get = lambda url, dest, tries=6: False if "/pdf/" in url else _g(url.replace("https://export.arxiv.org/e-print/", "https://arxiv.org/e-print/"), dest, tries)
TEMPLATE = open(os.path.join(HERE, "code", "prompt_template.md")).read(); PH = "{{PAPER_TEX}}"; assert TEMPLATE.count(PH) == 1
OUT = os.path.join(HERE, "out"); OPEN = os.path.join(HERE, "work", "open_shard.jsonl"); MISS = os.path.join(OUT, "missing.jsonl")


def git(*a, check=True):
    return subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True, check=check).stdout.strip()


def done_ids():
    d = set()
    for p in glob.glob(os.path.join(OUT, "prompts_*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            d |= {json.loads(l)["rq_id"] for l in f}
    if os.path.exists(OPEN):
        for l in open(OPEN, encoding="utf-8"):
            if l.endswith("\n"):
                d.add(json.loads(l)["rq_id"])
    if os.path.exists(MISS):
        d |= {m["rq_id"] for m in map(json.loads, filter(str.strip, open(MISS))) if not str(m.get("why", "")).startswith("error")}
    return d


def close_and_push(n, push):
    rows = [l for l in open(OPEN, encoding="utf-8") if l.endswith("\n")] if os.path.exists(OPEN) else []
    shard = None
    if rows:
        shard = os.path.join(OUT, time.strftime("prompts_%Y%m%d_%H%M%S.jsonl.gz"))
        with gzip.open(shard + ".part", "wt", encoding="utf-8") as f:
            f.writelines(rows)
        os.replace(shard + ".part", shard); os.remove(OPEN)
    json.dump({**n, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "shards": len(glob.glob(os.path.join(OUT, "prompts_*.jsonl.gz")))},
              open(os.path.join(OUT, "status.json"), "w"), indent=1)
    if not push:
        return
    git("add", "out");
    if git("status", "--porcelain", "out"):
        git("commit", "-qm", f"fetch: {n['ok']} prompts, {n['missing']} missing")
    for i in range(5):
        r = subprocess.run(["git", "-C", HERE, "push", "-q", "origin", "HEAD:main"], capture_output=True, text=True)
        if r.returncode == 0:
            break
        subprocess.run(["git", "-C", HERE, "pull", "-q", "--rebase", "origin", "main"], capture_output=True, text=True); time.sleep(10 * (i + 1))
    git("fetch", "-q", "origin", "main")
    ok = git("rev-parse", "HEAD") == git("rev-parse", "origin/main")
    if shard and ok and git("ls-tree", "origin/main", "out/" + os.path.basename(shard)):
        for l in rows:                                             # pushed and verified: drop the downloaded sources
            shutil.rmtree(FS.FR.folder(json.loads(l)["arxiv"]), ignore_errors=True)
    print(f"[{time.strftime('%H:%M:%S')}] push {'verified' if ok else 'NOT verified (will retry next round)'}", flush=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("-w", type=int, default=3); ap.add_argument("--chunk", type=int, default=30)
    ap.add_argument("--reverse", action="store_true"); ap.add_argument("--push-min", type=float, default=20); ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True); os.makedirs(FS.SIB, exist_ok=True)
    jobs, seen = [], set()
    for j in map(json.loads, open(os.path.join(HERE, "jobs.jsonl"), encoding="utf-8")):
        if j["rq_id"] not in seen:
            seen.add(j["rq_id"]); jobs.append(j)
    if a.reverse:                                                  # by group, so the other machine (front of the list) does not overlap
        gs = list(dict.fromkeys(j["gid"] for j in jobs))[::-1]; by = {}
        for j in jobs:
            by.setdefault(j["gid"], []).append(j)
        jobs = [j for g in gs for j in by[g]]
    done = done_ids(); todo = [j for j in jobs if j["rq_id"] not in done]
    print(f"jobs {len(jobs)} | already done {len(jobs) - len(todo)} | to do {len(todo)}", flush=True)
    n = {"ok": 0, "missing": 0, "errors": 0, "todo_at_start": len(todo)}; last = time.time(); ex = ThreadPoolExecutor(a.w)

    def get(j):
        try:
            _, st, ok = FS.one(j["arxiv"], {"title": j["title"], "targets": [f"seedtier/{j['gid']}"]})
        except Exception as e:
            return j, f"error {type(e).__name__}", None
        p = os.path.join(FS.FR.folder(j["arxiv"]), "ablation_inputs", "full_paper.tex")
        return j, st, (p if ok and os.path.getsize(p) >= 2000 else None)

    for s in range(0, len(todo), a.chunk):
        t0 = time.time()
        with open(OPEN, "a", encoding="utf-8") as f, open(MISS, "a") as fm:
            for j, st, p in ex.map(get, todo[s:s + a.chunk]):
                if p is None:
                    fm.write(json.dumps({"rq_id": j["rq_id"], "gid": j["gid"], "row": j["row"], "arxiv": j["arxiv"], "why": st}) + "\n")
                    n["errors" if str(st).startswith("error") else "missing"] += 1
                    if not str(st).startswith("error"):
                        shutil.rmtree(FS.FR.folder(j["arxiv"]), ignore_errors=True)
                else:
                    f.write(json.dumps({"rq_id": j["rq_id"], "arxiv": j["arxiv"], "title": j["title"], "groups": [j["gid"]], "row": j["row"],
                                        "corpus_rq": j["corpus_rq"], "prompt": TEMPLATE.replace(PH, open(p, encoding="utf-8", errors="replace").read().strip())},
                                       ensure_ascii=False) + "\n"); n["ok"] += 1
        print(f"[{time.strftime('%H:%M:%S')}] {min(s + a.chunk, len(todo))}/{len(todo)} | {n} | {time.time() - t0:.0f}s", flush=True)
        if time.time() - last > a.push_min * 60:
            close_and_push(n, not a.no_push); last = time.time()
    close_and_push(n, not a.no_push)
    open(os.path.join(OUT, "FETCH_DONE"), "w").write(json.dumps({**n, "time": time.strftime("%Y-%m-%d %H:%M:%S")}))
    close_and_push(n, not a.no_push); print("FETCH DONE", n, flush=True)


if __name__ == "__main__":
    main()
