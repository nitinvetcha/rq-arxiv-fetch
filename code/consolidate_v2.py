#!/usr/bin/env python3
"""Consolidate each paper's LaTeX source into one self-contained source/paper.tex (v2).

Pipeline per paper:
  1. pick the root file (\\begin{document}); a previously generated paper.tex is ignored,
     and papers that shipped their own paper.tex are read from paper.tex.orig.bak
  2. strip % comments and comment environments, leaving verbatim-like content untouched
  3. inline \\input/\\include/\\subfile/\\import/\\subimport and listing-file commands
     (\\lstinputlisting, \\verbatiminput, \\inputminted, custom \\newtcbinputlisting macros)
  4. drop dead \\iffalse / \\if 0 blocks, cut everything after the first \\end{document}
  5. embed references (.bbl if usable, else cited .bib entries rendered by hand)
"""
import os, re, sys, json, glob

BASE_VERB = {'verbatim', 'verbatim*', 'Verbatim', 'Verbatim*', 'BVerbatim', 'LVerbatim', 'lstlisting',
             'minted', 'tcblisting', 'alltt', 'spverbatim', 'filecontents', 'filecontents*'}
PH = '\x00V%d\x00'
PH_RE = re.compile('\x00V(\\d+)\x00')


def read_file(path):
    with open(path, 'rb') as f:
        b = f.read()
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('latin-1')


class Ctx:
    def __init__(self, src, rootdir, verb_envs, comment_envs, tcb_macros):
        self.src, self.rootdir = src, rootdir
        self.verb_envs, self.comment_envs, self.tcb = verb_envs, comment_envs, tcb_macros
        self.warn, self.included, self.store = [], set(), []
        self.stats = {'listings_inlined': 0, 'dead_blocks_removed': 0}

    def read(self, path):
        return read_paper_file(self.src, path)

    def protect(self, s):
        self.store.append(s)
        return PH % (len(self.store) - 1)


def read_paper_file(src, path):
    """paper.tex of papers that shipped their own is read from the backup."""
    bak = os.path.join(src, 'paper.tex.orig.bak')
    if os.path.abspath(path) == os.path.abspath(os.path.join(src, 'paper.tex')) and os.path.isfile(bak):
        return read_file(bak)
    return read_file(path)


# ---------------- argument parsing helpers ----------------

def skip_ws(t, i):
    while i < len(t) and t[i] in ' \t\n':
        i += 1
    return i


def read_group(t, i, open_ch='{', close_ch='}'):
    """t[i] must be open_ch. Returns (content, index after group) or (None, i). Brace-aware for []."""
    if i >= len(t) or t[i] != open_ch:
        return None, i
    depth, j = 0, i
    while j < len(t):
        c = t[j]
        if c == '\\':
            j += 2
            continue
        if open_ch == '[':
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            elif c == ']' and depth == 0:
                return t[i + 1:j], j + 1
        else:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return t[i + 1:j], j + 1
        j += 1
    return None, i


def read_opt(t, i):
    k = skip_ws(t, i)
    if k < len(t) and t[k] == '[':
        v, e = read_group(t, k, '[', ']')
        if v is not None:
            return v, e
    return None, i


def read_mand(t, i):
    k = skip_ws(t, i)
    return read_group(t, k)


def balanced(s):
    s = re.sub(r'\\.', '', s, flags=re.S)
    return s.count('{') == s.count('}')


# ---------------- comment stripping ----------------

TOK = re.compile(r'\\begin\s*\{(?P<env>[^{}]+)\}'
                 r'|\\(?:verb\*?|lstinline(?:\[[^\]]*\])?)(?P<d>[^a-zA-Z\s{*\[])'
                 r'|\\lstinline(?:\[[^\]]*\])?\{'
                 r'|\\(?:url|path|href|nolinkurl)\s*\{'
                 r'|\\.|%', re.S)


def strip_comments(txt, ctx):
    """Remove % comments and comment environments; verbatim-like bodies are stored verbatim
    behind placeholders so later passes cannot alter them."""
    out = []
    mode = None          # None | ('verb', env) | ('comment', env)
    res, vbuf, touched = '', [], False
    for line in txt.split('\n'):
        pos = 0
        if mode is None:
            res, touched = '', False
        while True:
            if mode is not None:
                endtag = '\\end{%s}' % mode[1]
                k = line.find(endtag, pos)
                if k == -1:
                    if mode[0] == 'verb':
                        vbuf.append(line[pos:])
                    break
                if mode[0] == 'verb':
                    vbuf.append(line[pos:k])
                    res += ctx.protect('\n'.join(vbuf)) + endtag
                    vbuf = []
                pos, mode = k + len(endtag), None
                continue
            m = TOK.search(line, pos)
            if m is None:
                res += line[pos:]
                break
            g = m.group(0)
            if g == '%':
                res += line[pos:m.start()]
                touched = True
                break
            env = m.group('env')
            if env is not None:
                env = env.strip()
                if env in ctx.comment_envs:
                    res += line[pos:m.start()]
                    mode, touched = ('comment', env), True
                    pos = m.end()
                    continue
                if env in ctx.verb_envs:
                    res += line[pos:m.end()]
                    mode, vbuf = ('verb', env), []
                    pos = m.end()
                    continue
                res += line[pos:m.end()]
                pos = m.end()
                continue
            if m.group('d') is not None:
                close = line.find(m.group('d'), m.end())
                if close == -1:
                    res += line[pos:]
                    break
                res += line[pos:close + 1]
                pos = close + 1
                continue
            if not g.startswith('\\lstinline') and g.endswith('{'):   # \url{..%..}: keep raw
                close = line.find('}', m.end())
                if close == -1:
                    res += line[pos:]
                    break
                res += line[pos:close + 1]
                pos = close + 1
                continue
            if g.startswith('\\lstinline'):
                close = line.find('}', m.end())
                if close == -1:
                    res += line[pos:]
                    break
                res += line[pos:close + 1]
                pos = close + 1
                continue
            res += line[pos:m.end()]          # escaped char such as \% or \\
            pos = m.end()
        if mode is not None:
            continue                          # line belongs to a multi-line verbatim/comment block
        if touched:
            res = res.rstrip()
            if not res.strip():
                continue                      # whole-line comment: drop the line
        out.append(res)
    if mode is not None:                      # unterminated block at EOF
        if mode[0] == 'verb':
            res += ctx.protect('\n'.join(vbuf))
        out.append(res)
    return '\n'.join(out)


# ---------------- dead conditional removal ----------------

COND_PRIM = {'if', 'ifx', 'ifnum', 'ifdim', 'ifodd', 'ifvmode', 'ifhmode', 'ifmmode', 'ifinner', 'ifcase',
             'ifcat', 'ifdefined', 'ifcsname', 'ifeof', 'ifvoid', 'ifhbox', 'ifvbox', 'iftrue', 'iffalse',
             'ifincsname', 'ifabsnum', 'ifabsdim', 'ifpdfprimitive'}
CTOK = re.compile(r'\\(if[a-zA-Z@]*|else|or|fi)(?![a-zA-Z@])')


def remove_dead_conditionals(txt, ctx, user_ifs):
    conds = COND_PRIM | user_ifs
    toks = []
    for m in CTOK.finditer(txt):
        name = m.group(1)
        pre = txt[max(0, m.start() - 40):m.start()]
        if re.search(r'\\(newif|let|def|edef|gdef|xdef|newcommand\*?|renewcommand\*?|providecommand\*?)\s*\{?\s*$', pre):
            continue                          # being defined/assigned, not executed
        if re.search(r'\\let\s*\\[a-zA-Z@]+\s*=?\s*$', pre):
            continue
        if name.startswith('if') and name not in conds:
            continue
        kind = name
        if name == 'if' and re.match(r'\s*0\s', txt[m.end():m.end() + 4]):
            kind = 'if0'
        toks.append((m.start(), m.end(), kind))
    cuts = []                                 # (start, end) spans to delete
    k = 0
    while k < len(toks):
        s, e, kind = toks[k]
        if kind not in ('iffalse', 'if0', 'iftrue'):
            k += 1
            continue
        depth, j, else_tok = 1, k + 1, None
        while j < len(toks) and depth:
            jk = toks[j][2]
            if jk == 'fi':
                depth -= 1
            elif jk == 'else' and depth == 1:
                else_tok = toks[j]
            elif jk.startswith('if') or jk == 'if0':
                depth += 1
            j += 1
        if depth:
            k += 1
            continue
        fi = toks[j - 1]
        start = s
        if kind == 'if0':
            start = s  # remove "\if 0" together with the false branch
        if kind == 'iftrue':
            spans = [(s, e)] + ([(else_tok[0], fi[1])] if else_tok else [(fi[0], fi[1])])
        elif else_tok:
            spans = [(start, else_tok[1]), (fi[0], fi[1])]
        else:
            spans = [(start, fi[1])]
        if all(balanced(txt[a:b]) for a, b in spans) and not any(a < c_end for a, _ in spans for _, c_end in cuts[-1:]):
            cuts.extend(spans)
            ctx.stats['dead_blocks_removed'] += 1
            k = j
        else:
            k += 1
    for a, b in sorted(cuts, reverse=True):
        txt = txt[:a] + txt[b:]
    return txt


# ---------------- include expansion ----------------

INC_CMDS = ['input', 'include', 'subfileinclude', 'subfile', 'subimport', 'import', 'includefrom', 'inputfrom',
            'lstinputlisting', 'verbatiminput', 'VerbatimInput', 'BVerbatimInput', 'LVerbatimInput', 'inputminted',
            'tcbinputlisting']
SKIP_EXT = re.compile(r'\.(sty|cls|bib|pgf|tikz|dat|csv)$')


def resolve(ctx, name, curdir, exts=('', '.tex')):
    name = name.strip().strip('"').strip()
    p = _resolve(ctx, name, curdir, exts)
    if p is None:                             # authors compiled on a case-insensitive file system
        if not hasattr(ctx, 'lower_files'):
            ctx.lower_files = {os.path.normpath(f).lower(): f for f in glob.glob(os.path.join(ctx.src, '**', '*'), recursive=True)
                               if os.path.isfile(f)}
        for base in (ctx.rootdir, curdir, ctx.src):
            q = os.path.normpath(os.path.join(base, name)).lower()
            for e in exts:
                if q + e in ctx.lower_files:
                    return ctx.lower_files[q + e]
    return p


def _resolve(ctx, name, curdir, exts):
    for base in (ctx.rootdir, curdir, ctx.src):
        p = os.path.normpath(os.path.join(base, name))
        for e in exts:
            if os.path.isfile(p + e):
                return p + e
            if os.path.abspath(p + e) == os.path.abspath(os.path.join(ctx.src, 'paper.tex')) and \
                    os.path.isfile(p + e + '.orig.bak'):
                return p + e                  # the author's own paper.tex, read from the backup
    return None


def listing_text(ctx, path, opts):
    t = read_file(path).replace('\r\n', '\n').rstrip('\n')
    fl = re.search(r'firstline\s*=\s*(\d+)', opts or '')
    ll = re.search(r'lastline\s*=\s*(\d+)', opts or '')
    if fl or ll:
        lines = t.split('\n')
        t = '\n'.join(lines[(int(fl.group(1)) - 1 if fl else 0):(int(ll.group(1)) if ll else None)])
    return t


def strip_key(opts, key):
    """remove `key={...}` or `key=value` from a tcolorbox option list."""
    i = 0
    while True:
        m = re.compile(r'(^|,)\s*' + re.escape(key) + r'\s*=\s*').search(opts, i)
        if not m:
            return opts
        j = m.end()
        if j < len(opts) and opts[j] == '{':
            _, e = read_group(opts, j)
        else:
            e = opts.find(',', j)
            e = len(opts) if e == -1 else e
        opts = opts[:m.start()] + (',' if m.group(1) else '') + opts[e:].lstrip(',')
        i = m.start()


def file_key(opts):
    m = re.search(r'listing file\s*=\s*', opts)
    if not m:
        return None
    j = m.end()
    if j < len(opts) and opts[j] == '{':
        v, _ = read_group(opts, j)
        return v
    e = opts.find(',', j)
    return opts[j:e if e != -1 else len(opts)].strip()


def expand(ctx, path, depth=0, subfile=False):
    txt = strip_comments(ctx.read(path), ctx)
    if depth > 0 and not subfile and re.search(r'\\documentclass', txt) and re.search(r'\\begin\{document\}', txt):
        subfile = True                        # a standalone document (e.g. a tikz figure): keep only its body
        ctx.stats['standalone_bodies'] = ctx.stats.get('standalone_bodies', 0) + 1
    if subfile:
        m = re.search(r'\\begin\{document\}', txt)
        if m:
            txt = txt[m.end():]
            txt = re.sub(r'\\end\{document\}.*', '', txt, flags=re.S)
    if depth > 15:
        ctx.warn.append('max depth at ' + path)
        return txt
    curdir = os.path.dirname(path)
    names = INC_CMDS + sorted(ctx.tcb)
    rx = re.compile(r'\\(' + '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r')(?![a-zA-Z@])(\*?)')
    out, pos = [], 0
    for m in rx.finditer(txt):
        if m.start() < pos:
            continue
        cmd, i = m.group(1), m.end()
        rep = None
        if cmd in ('input', 'include', 'subfile', 'subfileinclude'):
            arg, e = read_mand(txt, i)
            if arg is None:
                bm = re.match(r'[ \t]+([^\s{}\\]+)', txt[i:])
                if not bm or cmd != 'input':
                    continue
                arg, e = bm.group(1), i + bm.end()
            arg = arg.strip()
            if SKIP_EXT.search(arg) or '#' in arg:
                if '#' in arg:
                    ctx.warn.append('unresolved include: ' + arg)
                continue
            p = resolve(ctx, arg, curdir)
            if p is None:
                ctx.warn.append('unresolved include: ' + arg)
                continue
            ctx.included.add(os.path.relpath(p, ctx.src))
            rep = '\n' + expand(ctx, p, depth + 1, subfile=cmd in ('subfile', 'subfileinclude')) + '\n'
        elif cmd in ('subimport', 'import', 'includefrom', 'inputfrom'):
            d, e1 = read_mand(txt, i)
            f, e = read_mand(txt, e1) if d is not None else (None, i)
            if f is None:
                continue
            name = os.path.join(d.strip(), f.strip())
            p = resolve(ctx, name, curdir)
            if p is None:
                ctx.warn.append('unresolved include: ' + name)
                continue
            ctx.included.add(os.path.relpath(p, ctx.src))
            rep = '\n' + expand(ctx, p, depth + 1) + '\n'
        elif cmd in ('lstinputlisting', 'verbatiminput', 'VerbatimInput', 'BVerbatimInput', 'LVerbatimInput', 'inputminted'):
            opts, e0 = read_opt(txt, i)
            lang = None
            if cmd == 'inputminted':
                lang, e0 = read_mand(txt, e0)
            f, e = read_mand(txt, e0)
            if f is None or '#' in f:
                continue
            p = resolve(ctx, f.strip(), curdir, exts=('', '.tex', '.txt'))
            if p is None:
                ctx.warn.append('unresolved listing: ' + f.strip())
                continue
            env = {'lstinputlisting': 'lstlisting', 'verbatiminput': 'verbatim', 'inputminted': 'minted',
                   'VerbatimInput': 'Verbatim', 'BVerbatimInput': 'BVerbatim', 'LVerbatimInput': 'LVerbatim'}[cmd]
            head = '\\begin{%s}' % env + ('[%s]' % opts if opts is not None else '') + ('{%s}' % lang if lang else '')
            body = ctx.protect('\n' + listing_text(ctx, p, opts) + '\n')
            rep = head + body + '\\end{%s}' % env
            ctx.included.add(os.path.relpath(p, ctx.src))
            ctx.stats['listings_inlined'] += 1
        else:  # tcbinputlisting or a custom \newtcbinputlisting macro
            if cmd == 'tcbinputlisting':
                o, e = read_mand(txt, i)
                if o is None:
                    continue
                opts = o
            else:
                spec = ctx.tcb[cmd]
                args, e = [], i
                ok = True
                for kind, default in spec['args']:
                    if kind == 'o':
                        v, e = read_opt(txt, e)
                        args.append(default if v is None else v)
                    else:
                        v, e = read_mand(txt, e)
                        if v is None:
                            ok = False
                            break
                        args.append(v)
                if not ok:
                    continue
                opts = re.sub(r'#(\d)', lambda mm: args[int(mm.group(1)) - 1] if int(mm.group(1)) <= len(args) else '', spec['opts'])
            fname = file_key(opts)
            p = resolve(ctx, fname, curdir, exts=('', '.tex', '.txt')) if fname else None
            if p is None:
                ctx.warn.append('unresolved listing: %s' % fname)
                continue
            opts = strip_key(opts, 'listing file').strip().strip(',')
            rep = '\\begin{tcblisting}{%s}' % opts + ctx.protect('\n' + listing_text(ctx, p, None) + '\n') + '\\end{tcblisting}'
            ctx.included.add(os.path.relpath(p, ctx.src))
            ctx.stats['listings_inlined'] += 1
        out.append(txt[pos:m.start()])
        out.append(rep)
        pos = e
    out.append(txt[pos:])
    return ''.join(out)


# ---------------- per-paper definitions ----------------

def paper_defs(src, texfiles):
    allt = '\n'.join(read_paper_file(src, t) for t in texfiles)
    verb = set(BASE_VERB)
    verb |= set(re.findall(r'\\(?:lstnewenvironment|DefineVerbatimEnvironment|newtcblisting|NewTCBListing|DeclareTCBListing|RenewTCBListing|renewtcblisting)\s*(?:\[[^\]]*\])?\s*\{([A-Za-z*@]+)\}', allt))
    for opt, lang in re.findall(r'\\newminted\s*(?:\[([A-Za-z*]+)\])?\s*\{([A-Za-z0-9]+)\}', allt):
        verb.add(opt or lang + 'code')
    comment = {'comment'} | set(re.findall(r'\\excludecomment\s*\{([A-Za-z*]+)\}', allt))
    comment -= set(re.findall(r'\\includecomment\s*\{([A-Za-z*]+)\}', allt))
    tcb = {}
    for m in re.finditer(r'\\newtcbinputlisting', allt):
        i = m.end()
        init, i = read_opt(allt, i)                    # init options (e.g. auto counter)
        k = skip_ws(allt, i)
        nm = re.match(r'\{?\\([A-Za-z@]+)\}?', allt[k:])
        if not nm:
            continue
        i = k + nm.end()
        n, i2 = read_opt(allt, i)
        nargs = int(n) if n and n.strip().isdigit() else 0
        dflt, i3 = read_opt(allt, i2)
        opts, _ = read_mand(allt, i3)
        if opts is None:
            continue
        args = [('o', dflt)] + [('m', None)] * (nargs - 1) if dflt is not None and nargs else [('m', None)] * nargs
        opts = re.sub(r'(?<!\\)%[^\n]*', '', opts).strip()
        if init:
            opts = re.sub(r'(?<!\\)%[^\n]*', '', init).strip().rstrip(',') + ',\n  ' + opts
        tcb[nm.group(1)] = {'args': args, 'opts': opts}
    for m in re.finditer(r'\\(?:NewTCBInputListing|DeclareTCBInputListing)', allt):
        i = m.end()
        _, i = read_opt(allt, i)
        nm, i = read_mand(allt, i)
        spec, i = read_mand(allt, i)
        opts, _ = read_mand(allt, i)
        if nm is None or spec is None or opts is None:
            continue
        args = [('o', None) if c == 'o' else ('m', None) for c in re.findall(r'[om]', spec)]
        tcb[nm.strip().lstrip('\\')] = {'args': args, 'opts': opts}
    user_ifs = set(re.findall(r'\\newif\s*\\(if[a-zA-Z@]+)', allt))
    return verb, comment, tcb, user_ifs


# ---------------- bibliography ----------------

MONTHS = {m: m.capitalize() for m in ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')}


def bib_value(t, p, strings):
    """parse a bibtex value starting at t[p] (supports {..}, "..", numbers, @string macros, # concat)."""
    parts = []
    while p < len(t):
        p = skip_ws(t, p)
        if p >= len(t):
            break
        c = t[p]
        if c == '{':
            v, e = read_group(t, p)
            if v is None:
                v, e = t[p + 1:], len(t)
            parts.append(v)
            p = e
        elif c == '"':
            q, d = p + 1, 0
            while q < len(t):
                if t[q] == '\\':
                    q += 2
                    continue
                if t[q] == '{':
                    d += 1
                elif t[q] == '}':
                    d -= 1
                elif t[q] == '"' and d == 0:
                    break
                q += 1
            parts.append(t[p + 1:q])
            p = q + 1
        else:
            mm = re.match(r'[^\s,#}]+', t[p:])
            if not mm:
                break
            w = mm.group(0)
            parts.append(strings.get(w.lower(), MONTHS.get(w.lower(), w)))
            p += mm.end()
        p = skip_ws(t, p)
        if p < len(t) and t[p] == '#':
            p += 1
            continue
        break
    return ''.join(parts), p


def parse_bib(txt, strings):
    entries = {}
    for m in re.finditer(r'@(\w+)\s*([{(])', txt):
        typ = m.group(1).lower()
        if typ in ('comment', 'preamble'):
            continue
        i = m.end()
        depth, j = 1, i
        opener, closer = m.group(2), '}' if m.group(2) == '{' else ')'
        while j < len(txt) and depth:
            c = txt[j]
            if c == '\\':
                j += 2
                continue
            if c == opener or (opener == '(' and c == '{'):
                depth += 1 if c == opener else 0
            if c == closer:
                depth -= 1
            j += 1
        body = txt[i:j - 1]
        if typ == 'string':
            sm = re.match(r'\s*(\w[\w\-:.]*)\s*=\s*', body)
            if sm:
                strings[sm.group(1).lower()] = bib_value(body, sm.end(), strings)[0]
            continue
        km = re.match(r'\s*([^,\s]+)\s*,', body)
        if not km:
            continue
        key, p, fields = km.group(1), km.end(), {}
        while p < len(body):
            fm = re.compile(r'\s*,?\s*([\w\-:.]+)\s*=\s*').match(body, p)
            if not fm:
                break
            v, p = bib_value(body, fm.end(), strings)
            k = fm.group(1).lower()
            if k not in fields:
                fields[k] = re.sub(r'\s+', ' ', v).strip()
            p = skip_ws(body, p)
            if p < len(body) and body[p] == ',':
                p += 1
        entries[key] = (typ, fields)
    return entries


def fmt_names(s):
    names = [n.strip() for n in re.split(r'\s+and\s+', s) if n.strip()]
    if names and names[-1].lower() == 'others':
        return ', '.join(names[:-1]) + ' et al.'
    return ', '.join(names)


def fmt_entry(key, typ, f):
    g = lambda k: f.get(k, '').strip()
    parts = []
    if g('author'):
        parts.append(fmt_names(g('author')).rstrip('.') + '.')
    elif g('editor'):
        parts.append(fmt_names(g('editor')) + ' (eds.).')
    if g('title'):
        parts.append(g('title').rstrip('.') + '.')
    venue = g('journal') or g('booktitle') or g('howpublished') or g('publisher') or g('school') or g('institution')
    if venue:
        v = venue
        if g('volume'):
            v += ' ' + g('volume')
        if g('number'):
            v += '(' + g('number') + ')'
        if g('pages'):
            v += ', ' + g('pages')
        parts.append(v + '.')
    if g('year'):
        parts.append(g('year') + '.')
    if g('eprint'):
        parts.append('arXiv:' + g('eprint') + '.')
    elif g('url'):
        parts.append('\\url{%s}' % g('url'))
    elif g('doi'):
        parts.append('doi:' + g('doi'))
    return '\\bibitem{%s} %s' % (key, ' '.join(parts))


CITE_SKIP = {'setcitestyle', 'citestyle', 'citeindextrue', 'citeindexfalse', 'citeindextype'}


def cited_keys(txt):
    keys, nocite_all = [], False
    for m in re.finditer(r'\\([a-zA-Z]*[cC]ite[a-zA-Z]*)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]+)\}', txt):
        if m.group(1) in CITE_SKIP:
            continue
        for k in m.group(2).split(','):
            k = k.strip()
            if k == '*':
                nocite_all = True
            elif k and '#' not in k and '\\' not in k and k not in keys:
                keys.append(k)
    return keys, nocite_all


def bib_block(ctx, txt, bibnames):
    entries, strings = {}, {}
    files = []
    for n in bibnames:
        n = n.strip()
        if not n:
            continue
        p = resolve(ctx, n if n.endswith('.bib') else n + '.bib', ctx.rootdir, exts=('',))
        if p:
            files.append(p)
        else:
            ctx.warn.append('bib not found: ' + n)
    for p in files:                       # pass 1: collect @string macros from every file
        parse_bib(read_file(p), strings)
    for p in files:
        for k, v in parse_bib(read_file(p), strings).items():
            entries.setdefault(k, v)
    if not entries:
        return None
    keys, allc = cited_keys(txt)
    lower = {}
    for k in entries:                     # bibtex matches keys case-insensitively
        lower.setdefault(k.lower(), k)
    find = lambda k: k if k in entries else lower.get(k.lower())
    if allc or not keys:
        sel = [(k, k) for k in entries]
    else:
        sel, seen = [], set()
        for k in keys:
            e = find(k)
            if e and e not in seen:
                seen.add(e)
                sel.append((k, e))        # keep the spelling used in \cite
    missing = [k for k in keys if not find(k)]
    if missing:
        ctx.warn.append('cited keys missing from bib: %d' % len(missing))
    lines = ['\\begin{thebibliography}{%d}' % len(sel)]
    lines += [fmt_entry(k, *entries[e]) for k, e in sel]
    lines.append('\\end{thebibliography}')
    return '\n'.join(lines)


def bbl_keys(t):
    return set(re.findall(r'\\bibitem\s*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?\s*\{([^}]+)\}', t)) | set(re.findall(r'\\bib\{([^}]+)\}', t))


def find_bbl(ctx, rootfile, txt):
    base = os.path.splitext(rootfile)[0] + '.bbl'
    cands = [base] + sorted(glob.glob(os.path.join(ctx.src, '**', '*.bbl'), recursive=True))
    keys = set(cited_keys(txt)[0])
    best, best_score = None, -1
    for idx, c in enumerate(cands):
        if not os.path.isfile(c):
            continue
        t = read_file(c)
        if not ('\\bibitem' in t or '\\begin{bibdiv}' in t or '\\begin{thebibliography}' in t):
            continue                      # e.g. biblatex .bbl: fall back to the .bib
        score = len(keys & bbl_keys(t)) if keys else 0
        if score > best_score:
            best, best_score = t, score
    return best


BIBCMD = re.compile(r'\\bibliography\s*\{([^{}]*)\}|\\printbibliography(?:\[[^\]]*\])?')


def embed_refs(ctx, txt, rootfile):
    has_inline = re.search(r'\\begin\{thebibliography\}|\\begin\{bibdiv\}', txt)
    if has_inline and not BIBCMD.search(txt):
        return txt, 'inline'
    bbl = find_bbl(ctx, rootfile, txt)
    if bbl is not None:
        block, how = bbl.strip(), 'bbl'
    else:
        names = []
        for m in re.finditer(r'\\bibliography\s*\{([^{}]*)\}', txt):
            names += m.group(1).split(',')
        for m in re.finditer(r'\\addbibresource(?:\[[^\]]*\])?\s*\{([^{}]*)\}', txt):
            names.append(m.group(1))
        if not names:
            names = [os.path.relpath(p, ctx.rootdir) for p in glob.glob(os.path.join(ctx.src, '**', '*.bib'), recursive=True)]
        block = bib_block(ctx, txt, names) if names else None
        how = 'bib-rendered'
    if block is None:
        return txt, 'inline' if has_inline else 'none'
    if has_inline:
        how += '+inline'
    if BIBCMD.search(txt):
        txt = BIBCMD.sub(lambda m: block, txt, count=1)
        txt = BIBCMD.sub('', txt)
    else:
        idx = txt.rfind('\\end{document}')
        txt = txt[:idx] + '\n' + block + '\n' + txt[idx:] if idx != -1 else txt + '\n' + block
    return txt, how


# ---------------- driver ----------------

OVERRIDES = {'2605.14038': 'camera_ready.tex', '2605.30329': 'main.tex'}


def find_root(src, texfiles, ctx_for_strip):
    stripped = {t: strip_comments(read_paper_file(src, t), ctx_for_strip) for t in texfiles}
    cands = [t for t in texfiles if re.search(r'\\begin\{document\}', stripped[t])]
    dc = [t for t in cands if re.search(r'\\documentclass', stripped[t])]
    cands = dc or cands
    if not cands:
        return None, 'no root'
    if len(cands) == 1:
        return cands[0], ''
    ov = OVERRIDES.get(os.path.basename(os.path.dirname(src)))
    if ov:
        return os.path.join(src, ov), 'manual override'
    allt = ' '.join(stripped.values())
    free = [c for c in cands if not re.search(r'\\(input|include|subfile)\s*\{[^}]*%s(\.tex)?\s*\}' % re.escape(os.path.splitext(os.path.basename(c))[0]), allt)]
    pool = free or cands
    pref = [c for c in pool if os.path.basename(c).lower() in ('main.tex', 'paper.tex', 'ms.tex', 'manuscript.tex')]
    pool = pref or pool
    pool.sort(key=lambda c: -len(stripped[c]))
    return pool[0], 'multiple roots: ' + ', '.join(os.path.relpath(c, src) for c in cands)


def list_tex(src):
    out_path = os.path.join(src, 'paper.tex')
    has_bak = os.path.isfile(out_path + '.orig.bak')
    tex = [t for t in glob.glob(os.path.join(src, '**', '*.tex'), recursive=True)
           if os.path.abspath(t) != os.path.abspath(out_path)]
    if has_bak:
        tex.append(out_path)               # read from the backup via read_paper_file
    return sorted(tex)


def process(src, write=True):
    out_path = os.path.join(src, 'paper.tex')
    texfiles = list_tex(src)
    if not texfiles:
        return {'status': 'no_tex'}
    verb, comment, tcb, user_ifs = paper_defs(src, texfiles)
    root, note = find_root(src, texfiles, Ctx(src, src, verb, comment, tcb))
    if root is None:
        return {'status': 'no_root'}
    ctx = Ctx(src, os.path.dirname(root), verb, comment, tcb)
    ctx.included.add(os.path.relpath(root, src))
    txt = expand(ctx, root)
    txt = remove_dead_conditionals(txt, ctx, user_ifs)
    m = re.search(r'\\end\{document\}', txt)
    truncated = False
    if m:
        truncated = bool(txt[m.end():].strip())
        txt = txt[:m.end()]
    txt, how = embed_refs(ctx, txt, root)
    txt = re.sub(r'\n{3,}', '\n\n', txt).strip() + '\n'
    for _ in range(3):                       # placeholders can nest (listing inside stored text is not expected)
        txt = PH_RE.sub(lambda mm: ctx.store[int(mm.group(1))], txt)
    if write:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(txt)
    return {'status': 'ok', 'root': os.path.relpath(root, src), 'note': note, 'files_merged': len(ctx.included),
            'tex_total': len(texfiles), 'refs': how, 'warnings': ctx.warn, 'chars': len(txt),
            'truncated_after_end_document': truncated, **ctx.stats, **({} if write else {'_text': txt})}


if __name__ == '__main__':
    base, report = sys.argv[1], sys.argv[2]
    res = {}
    for d in sys.argv[3:]:
        for p in sorted(glob.glob(os.path.join(base, d, '*', 'source'))):
            pid = d.split('/')[0] + '/' + os.path.basename(os.path.dirname(p))
            try:
                res[pid] = process(p)
            except Exception as e:
                import traceback
                res[pid] = {'status': 'error', 'error': repr(e), 'tb': traceback.format_exc()[-600:]}
    json.dump(res, open(report, 'w'), indent=1)
    from collections import Counter
    print(Counter(r['status'] for r in res.values()))
    print(Counter(r.get('refs') for r in res.values()))
