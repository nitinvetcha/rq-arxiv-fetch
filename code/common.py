"""Shared helpers: API key rotation (keys are read from ~/.s2_env*, ~/.openalex_env*, never printed),
paper listing and title normalisation."""
import glob, os, re, threading, time, unicodedata, json
import requests

BASE = os.environ.get('RQF_WORK', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'work'))  # standalone: scratch store (not committed)
COLLECTIONS = ['neurips_papers', 'scholar_catalyst']
UA = {'User-Agent': 'research-benchmark-fetch/1.0'}


def target_papers():
    out = []
    for c in COLLECTIONS:
        for d in sorted(glob.glob(os.path.join(BASE, c, 'papers', '*'))):
            if os.path.isfile(os.path.join(d, 'source', 'paper.tex')):
                out.append((c, os.path.basename(d), d))
    return out


def _load(pattern, var):
    keys = []
    for p in sorted(glob.glob(os.path.expanduser(pattern))):
        for line in open(p):
            if line.strip().startswith(var + '='):
                v = line.split('=', 1)[1].strip().strip('"\'')
                if v:
                    keys.append(v)
    return keys


class KeyPool:
    """Round-robin keys, each limited to `rate` requests / second."""
    def __init__(self, keys, rate=1.0):
        self.keys, self.gap = keys, 1.0 / rate
        self.last = [0.0] * len(keys)
        self.i, self.lock = 0, threading.Lock()

    def take(self):
        with self.lock:
            while True:
                now = time.time()
                best = min(range(len(self.keys)), key=lambda k: self.last[k])
                wait = self.last[best] + self.gap - now
                if wait <= 0:
                    self.last[best] = now
                    return self.keys[best]
                time.sleep(min(wait, 0.2))

    def penalize(self, key, secs):
        with self.lock:
            k = self.keys.index(key)
            self.last[k] = max(self.last[k], time.time() + secs)


S2 = KeyPool(_load('~/.s2_env*', 'S2_API_KEY'), rate=0.9)
OA = KeyPool(_load('~/.openalex_env*', 'OPENALEX_API_KEY'), rate=8)


def s2_get(path, params=None, tries=25):
    url = 'https://api.semanticscholar.org/graph/v1/' + path
    for t in range(tries):
        key = S2.take()
        try:
            r = requests.get(url, params=params, headers={'x-api-key': key, **UA}, timeout=60)
        except Exception:
            time.sleep(2 + t)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (400, 404):
            return None
        if r.status_code == 429:
            S2.penalize(key, 20)
        else:
            time.sleep(min(30, 2 * (t + 1)))
    raise RuntimeError('s2 failed %s' % path)


def s2_post(path, params, body, tries=25):
    url = 'https://api.semanticscholar.org/graph/v1/' + path
    for t in range(tries):
        key = S2.take()
        try:
            r = requests.post(url, params=params, json=body, headers={'x-api-key': key, **UA}, timeout=120)
        except Exception:
            time.sleep(2 + t)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (400, 404):
            return None
        if r.status_code == 429:
            S2.penalize(key, 20)
        else:
            time.sleep(min(30, 2 * (t + 1)))
    raise RuntimeError('s2 post failed')


def oa_get(path, params=None, tries=6):
    params = dict(params or {})
    for t in range(tries):
        params['api_key'] = OA.take()
        try:
            r = requests.get('https://api.openalex.org/' + path, params=params, headers=UA, timeout=60)
        except Exception:
            time.sleep(2 + t)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (400, 404):
            return None
        time.sleep(1.5 * (t + 1))
    return None


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'\\[a-zA-Z]+\s*', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def jdump(obj, path):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
