# rq-arxiv-fetch

Fetch the arXiv LaTeX of 6,592 follow-up papers (1,583 RQB task-7 groups) and build their RQ-recovery prompts.
The code is the same as the RQB pipeline (`followups.py`), with no PDFs and the `arxiv.org/e-print` host.
The output was checked to be byte-identical to that pipeline.

## Run

```bash
git clone https://github.com/nitinvetcha/rq-arxiv-fetch && cd rq-arxiv-fetch
python3 -m pip install --user requests          # only dependency (Python >= 3.8)
nohup python3 -I fetch_jobs.py -w 3 --reverse --push-min 20 > fetch.log 2>&1 &
```

* `--reverse` processes the groups from the end of `jobs.jsonl`. The RQB machine is working from the front, so the two don't overlap.
* Every 20 min the finished prompts are gzipped into `out/prompts_<stamp>.jsonl.gz`, committed and pushed to `main`. Once the push is
  verified, the downloaded sources for those papers are deleted from `work/`.
* `out/missing.jsonl` lists papers with no usable LaTeX. Rows whose `why` starts with `error` (network) are retried on the next start.
* It is resumable. Rerun the same command after a crash, and again at the end until a run reports `to do 0` or only errors remain.
* `out/FETCH_DONE` is written when a pass is complete.
* Keep 3 workers (arXiv rate limits). The code refuses to download if fewer than 30 GB are free.
