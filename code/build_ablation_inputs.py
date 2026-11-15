"""Build ablation inputs from each paper's single-file paper.tex.

For every <root>/papers/<id>/source/paper.tex this writes <root>/papers/<id>/ablation_inputs/:
  full_paper.tex                  title + abstract + all sections + appendix (no bibliography / checklist)
  method.tex                      main-body method sections
  experiments.tex                 main-body experiment / results sections
  related_work.tex                main-body related work / background / preliminaries sections
  abstract_intro_conclusion.tex   abstract + introduction + conclusion/discussion/limitations/future work
  method_experiments.tex          method + experiments
  related_method_experiments.tex  related work + method + experiments
  sections.json                   how every section was labelled (for auditing)
Partial inputs use main-body sections in paper order. If a paper has no main-body section for a
component (e.g. related work moved to the appendix), appendix sections whose titles match are used instead.
A summary of all papers goes to ablation_inputs_summary.csv.
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOTS = ["neurips_papers/papers", "scholar_catalyst/papers"]

VARIANTS = {
    "method": ["method"],
    "experiments": ["experiments"],
    "related_work": ["related"],
    "abstract_intro_conclusion": ["abstract", "intro", "conclusion"],
    "method_experiments": ["method", "experiments"],
    "related_method_experiments": ["related", "method", "experiments"],
}

# ---------- LaTeX helpers ----------

def strip_comments(text):
    out = []
    for line in text.split("\n"):
        m = re.search(r"(?<!\\)%", line)
        if m:
            if line[: m.start()].strip() == "":
                continue  # whole-line comment
            line = line[: m.start()]
        out.append(line)
    return "\n".join(out)


def match_brace(text, i):
    """text[i] == '{'; return index just past the matching '}'."""
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(text)


def plain(title):
    t = re.sub(r"\\[a-zA-Z@]+\*?", " ", title)
    t = re.sub(r"[{}$~\\]", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


SECTION_RE = re.compile(r"\\section\*?\s*(\[[^\]]*\])?\s*\{")


def section_regex(full):
    """\\section plus any one-argument wrapper macro, e.g. \\newcommand{\\tightsection}[1]{...\\section{#1}...}."""
    names = []
    for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([a-zA-Z]+)\}?\s*\[1\]\s*\{", full):
        defn = full[m.end() - 1: match_brace(full, m.end() - 1)]
        if re.search(r"\\section\*?\s*\{\s*#1\s*\}", defn):
            names.append(m.group(1))
    if not names:
        return SECTION_RE
    alt = "|".join(["section\\*?"] + [re.escape(n) + r"(?![a-zA-Z])" for n in names])
    return re.compile(r"\\(?:" + alt + r")\s*(\[[^\]]*\])?\s*\{")


def find_sections(body, sec_re=SECTION_RE):
    secs = []
    for m in sec_re.finditer(body):
        end = match_brace(body, m.end() - 1)
        secs.append({"start": m.start(), "title_raw": body[m.end(): end - 1]})
    for k, s in enumerate(secs):
        s["end"] = secs[k + 1]["start"] if k + 1 < len(secs) else len(body)
        s["title"] = plain(s["title_raw"])
    return secs


BIB_RES = [
    re.compile(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.S),
    re.compile(r"\\bibliography\{[^}]*\}"),
    re.compile(r"\\printbibliography(\[[^\]]*\])?"),
    re.compile(r"\\bibliographystyle\{[^}]*\}"),
]


def bib_start(body):
    pos = [m.start() for r in BIB_RES[:3] for m in r.finditer(body)]
    return min(pos) if pos else None


def remove_bib(text):
    for r in BIB_RES:
        text = r.sub("", text)
    return text

# ---------- abstract / title ----------

DEF_PREFIX = re.compile(r"\\(newcommand|renewcommand|providecommand|def|newenvironment|renewenvironment)\*?\s*\{?\s*$")


def resolve_macro(content, full):
    """If content is just a macro like \\abstractcontent, return its \\newcommand body."""
    m = re.fullmatch(r"\s*\\([a-zA-Z@]+)\s*", content)
    if not m:
        return content
    d = re.search(r"\\(?:newcommand|renewcommand|def)\s*\{?\\" + m.group(1) + r"\}?\s*\{", full)
    if not d:
        return content
    return full[d.end(): match_brace(full, d.end() - 1) - 1]


def find_abstract(full, body, first_sec_pos):
    # 1) any environment whose name contains "abstract" (abstract, icmlabstract, abstractblock, ...)
    for where, src in (("", body), ("preamble-", full)):
        for m in re.finditer(r"\\begin\{(\w*abstract\w*)\}", src):
            name = m.group(1)
            e = src.find("\\end{" + name + "}", m.end())
            if e != -1:
                txt = resolve_macro(src[m.end(): e].strip(), full)
                txt = re.sub(r"^\\textbf\{\s*Abstract\s*\}\s*(\\\\)?", "", txt.strip())
                return txt.strip(), where + "env:" + name
    # 2) command form: \abstract{...}, \setabstract{...}, \abstracttext{...}
    for m in re.finditer(r"\\(abstract|setabstract|abstracttext)\s*\{", full):
        if DEF_PREFIX.search(full[max(0, m.start() - 40): m.start()]):
            continue
        end = match_brace(full, m.end() - 1)
        return full[m.end(): end - 1].strip(), "cmd:" + m.group(1)
    # 3) \section*{Abstract}
    m = re.search(r"\\section\*?\s*\{\s*abstract\s*\}", body, re.I)
    if m:
        nxt = SECTION_RE.search(body, m.end())
        return body[m.end(): nxt.start() if nxt else len(body)].strip(), "section"
    # 4) a paragraph starting with a bold/plain "Abstract" label before the first section
    pre = body[:first_sec_pos]
    m = re.search(r"(\{?\\textbf\{\s*(\\emph\{)?\s*Abstract[:.]?\s*\}?\s*\}\}?|\bAbstract[:.])", pre)
    if m:
        para = re.split(r"\n\s*\n", pre[m.end():].lstrip(), maxsplit=1)[0]
        return para.strip(), "labelled-paragraph"
    # 5) text between \maketitle and the first section (e.g. italic summary paragraph)
    m = re.search(r"\\maketitle", pre)
    if m:
        txt = pre[m.end():]
        txt = re.sub(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", "", txt, flags=re.S).strip()
        if 200 < len(txt) < 5000:
            return txt, "after-maketitle"
    return "", "none"


def find_title(full):
    m = re.search(r"\\title\s*(\[[^\]]*\])?\s*\{", full)
    if not m:
        return ""
    return full[m.end(): match_brace(full, m.end() - 1) - 1].strip()

# ---------- section classification ----------

def kw(title, words):
    return any(re.search(w, title) for w in words)


OTHER = [r"^acknowledg", r"checklist", r"impact statement", r"^ethic", r"ethics statement",
         r"ethical (consideration|statement)", r"^reproducibility", r"reproducibility statement",
         r"llm usage", r"use of (large language models|llms)", r"usage of llm", r"^compute resources",
         r"^computational resources", r"author contribution", r"^funding", r"^broader impact",
         r"^societal impact", r"^licen[cs]e", r"^disclosure", r"^declaration", r"data availability",
         r"code availability", r"^(table of )?contents?$", r"^appendix contents",
         r"use statement", r"contribution statement", r"usage disclosure", r"^software and data$"]
APPENDIX_TITLES = [r"^appendix", r"^appendices", r"supplementary", r"^supplemental"]
INTRO = [r"introduction", r"^overview$"]
CONCL = [r"conclu", r"concluding", r"^summary", r"^limitation", r"limitations?$",
         r"limitations?,", r"^(future work|future direction)", r"future (work|directions?)$",
         r"^discussion", r"discussion$", r"^outlook", r"closing remarks", r"final remarks"]
RELATED = [r"related", r"prior work", r"previous work", r"literature", r"background",
           r"preliminar", r"existing work"]
EXPER = [r"experiment(s|al)?\b", r"result", r"^rq\s?\d", r"research question", r"evaluation", r"empirical", r"ablation", r"case stud",
         r"benchmarking", r"simulation", r"^analysis", r"analyses", r"comparison", r"findings",
         r"performance", r"implementation detail", r"\bstudies\b", r"\bstudy\b"]
METHOD = [r"method", r"approach", r"proposed", r"framework", r"algorithm", r"architecture",
          r"formulation", r"problem (setup|setting|statement|definition)", r"theor", r"model",
          r"notation", r"motivation", r"design", r"pipeline", r"^our ", r"technique",
          r"solution", r"mechanism"]


def classify_by_title(t):
    if re.match(r"limitation", t):
        return "conclusion"
    if kw(t, OTHER):
        return "other"
    if kw(t, INTRO):
        return "intro"
    if re.search(r"conclu", t):
        return "conclusion"
    if kw(t, RELATED) and not kw(t, [r"experiment", r"result"]):
        return "related"
    if re.search(r"proposed|^our ", t):
        return "method"
    if re.search(r"theoretical analysis|analysis of (the )?(method|algorithm)", t):
        return "method"
    if kw(t, EXPER):
        return "experiments"
    if kw(t, CONCL):
        return "conclusion"
    if kw(t, METHOD):
        return "method"
    return None


def classify_main(secs):
    for s in secs:
        s["label"] = classify_by_title(s["title"])
        s["how"] = "title" if s["label"] else "position"
    labels = [s["label"] for s in secs]
    exp_idx = [i for i, l in enumerate(labels) if l == "experiments"]
    core = [i for i, l in enumerate(labels) if l in ("intro", "method", "experiments")]
    # closing block = conclusion-labelled sections after which no intro/method/experiments occurs
    closing_from = next((i for i, l in enumerate(labels)
                         if l == "conclusion" and all(c < i for c in core)), len(secs))
    # a plain "Method" heading with no experiments section: unnamed sections after it are the studies
    plain_method = next((i for i, s in enumerate(secs)
                         if re.fullmatch(r"(our |proposed )?(methods?|methodology|approach)", s["title"])), None)
    for i, s in enumerate(secs):
        if s["label"]:
            continue
        if i > closing_from:
            s["label"] = "conclusion"
        elif exp_idx and i > exp_idx[-1]:
            s["label"] = "experiments"   # continues the results
        elif exp_idx:
            s["label"] = "method"        # sits before the experiments
        elif plain_method is not None and i > plain_method:
            s["label"] = "experiments"
        else:
            s["label"] = "method"

# ---------- per-paper processing ----------

def process(tex_path):
    raw = tex_path.read_text(encoding="utf-8", errors="replace")
    full = strip_comments(raw)
    b = full.find("\\begin{document}")
    e = full.rfind("\\end{document}")
    body = full[b + len("\\begin{document}"): e if e != -1 else len(full)] if b != -1 else full

    secs = find_sections(body, section_regex(full))
    first_sec_pos = secs[0]["start"] if secs else len(body)
    abstract, abs_how = find_abstract(full, body, first_sec_pos)
    title = find_title(full)

    # appendix boundary: \appendix, \begin{appendices}, an "Appendix" heading, else bibliography
    cands = [m.start() for m in re.finditer(r"\\appendix\b|\\begin\{appendices\}", body)]
    cands += [s["start"] for s in secs if kw(s["title"], APPENDIX_TITLES)]
    bib = bib_start(body)
    app_pos = min(cands) if cands else None
    app_how = "marker" if cands else None
    if app_pos is None and bib is not None and any(s["start"] > bib for s in secs):
        app_pos, app_how = bib, "after-bibliography"
    if app_pos is None:
        app_pos = len(body)

    for s in secs:
        s["text"] = remove_bib(body[s["start"]: s["end"]]).strip()
        s["in_appendix"] = s["start"] >= app_pos
    main = [s for s in secs if not s["in_appendix"] and s["title"] != "abstract"]
    classify_main(main)
    for s in secs:
        if s["in_appendix"]:
            s["label"], s["how"] = ("other", "title") if kw(s["title"], OTHER) else ("appendix", "position")

    abs_block = "\\begin{abstract}\n" + abstract + "\n\\end{abstract}" if abstract else ""

    # if a component is missing from the main body, fall back to appendix sections with matching titles
    fallback = {}
    for lab in ("related", "method", "experiments"):
        if not any(s["label"] == lab for s in main):
            fallback[lab] = [s for s in secs if s["in_appendix"] and classify_by_title(s["title"]) == lab
                             and "checklist" not in s["title"]]
            for s in fallback[lab]:
                s["used_as"] = lab

    def join(labels):
        parts = []
        if "abstract" in labels and abs_block:
            parts.append(abs_block)
        for s in secs:
            if not s["in_appendix"] and s["title"] != "abstract" and s["label"] in labels:
                parts.append(s["text"])
        for lab in labels:
            parts += [s["text"] for s in fallback.get(lab, [])]
        return "\n\n".join(parts).strip() + "\n"

    outputs = {k: join(v) for k, v in VARIANTS.items()}
    full_parts = []
    if title:
        full_parts.append("\\title{" + title + "}")
    if abs_block:
        full_parts.append(abs_block)
    if app_pos < len(body) and app_how == "marker":
        full_parts += [s["text"] for s in secs if not s["in_appendix"] and s["title"] != "abstract"
                       and "checklist" not in s["title"]]
        full_parts.append("\\appendix")
        full_parts += [s["text"] for s in secs if s["in_appendix"] and "checklist" not in s["title"]]
    else:
        full_parts += [s["text"] for s in secs
                       if s["title"] != "abstract" and "checklist" not in s["title"]]
    outputs = {"full_paper": "\n\n".join(full_parts).strip() + "\n", **outputs}

    out_dir = tex_path.parent.parent / "ablation_inputs"
    out_dir.mkdir(exist_ok=True)
    for name, text in outputs.items():
        (out_dir / f"{name}.tex").write_text(text, encoding="utf-8")
    manifest = {
        "paper": tex_path.parent.parent.name,
        "abstract_found_via": abs_how,
        "appendix_found_via": app_how,
        "sections": [{"title": s["title_raw"].strip(), "label": s["label"], "labelled_by": s["how"],
                      "in_appendix": s["in_appendix"], "chars": len(s["text"]),
                      **({"used_as_fallback_for": s["used_as"]} if "used_as" in s else {})} for s in secs],
        "output_chars": {k: len(v.strip()) for k, v in outputs.items()},
    }
    (out_dir / "sections.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    rows = []
    for root in ROOTS:
        for tex in sorted((base / root).glob("*/source/paper.tex")):
            m = process(tex)
            rows.append({"collection": root.split("/")[0], "paper": m["paper"],
                         "abstract_via": m["abstract_found_via"],
                         "appendix_via": m["appendix_found_via"] or "none",
                         **{k: v for k, v in m["output_chars"].items()}})
    with open(base / "ablation_inputs_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"processed {len(rows)} papers")
    for k in ["full_paper"] + list(VARIANTS):
        empty = [r["paper"] for r in rows if r[k] == 0]
        print(f"  {k:30s} empty in {len(empty):3d}  {empty[:8]}")
    print("  no abstract:", [r["paper"] for r in rows if r["abstract_via"] == "none"])


if __name__ == "__main__":
    main()
