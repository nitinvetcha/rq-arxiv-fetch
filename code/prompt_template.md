You are an expert in machine learning research. You will be given the full LaTeX source of ONE research paper. Your job is to recover the **underlying research question** of the paper, meaning the actual thinking that motivated the work, rather than just paraphrasing its abstract, introduction or conclusion.

Write the question **the way the authors would have framed it while doing the work**, not as it appears in the paper. A paper is written after the work is done: it presents a finished method, reports results, and is often framed to sell the contribution. The question you are asked for is the one the authors had in mind **when they started**: what they wanted to find out, build or understand, before they knew the answer. A rough, informal phrasing is fine, as long as it is the question that actually motivated the work.

You are asked for:

- **The primary research question** the authors were pursuing in this paper, and
- **Any secondary research questions**, if applicable.

---

# 0. The most important rule: the question as it stood before the work

The paper tells you what was done and what was found. You must work backwards to what was being asked. Restating the paper's own summary of itself as a question is a **failure** at this task, even if every fact in it is correct. Apply all of the following rules strictly, to the primary and to every secondary question.

1. **No results.** Do not include findings, numbers, success claims or conclusions ("achieves state-of-the-art", "we show that X holds", "significantly improves", "turns out to be"). The question is open; the paper is its answer. Do not phrase the question so that it presupposes the answer the paper reached.
2. **No names the paper coins.** Do not use the name of the method, model, dataset, benchmark, metric or concept that the paper introduces (e.g. a new acronym such as "FooNet" or "BarBench"). Those names did not exist when the question was asked. If the authors started from a specific idea, describe the idea in plain technical words instead. Names of **pre-existing** artifacts the work is about (an existing model, dataset, benchmark or method from prior work) are fine.
3. **No design details of the final solution.** Architecture choices, loss terms, training recipes, hyperparameters, implementation tricks and engineering decisions worked out along the way are part of the answer, not the question. If the authors set out to try a specific core idea ("what if we used X for Y?", "does factor X cause Y?"), you may state that idea at the level of the idea. If they started from an open problem and the method is what they arrived at, do **not** mention the method at all.
4. **Not the contribution list.** "We propose X, we prove Y, we evaluate on Z, we release W" describes the outputs of the work. Ask: *what question were these outputs meant to answer?* and write that question. Do not enumerate contributions, and do not turn each contribution into a clause of the question.
5. **Do not fall back on rephrasing the abstract, introduction or conclusion.** Those sections summarize what was done and found, and turning that summary into a question ("Can we propose X that achieves Y?") is not the answer. Treat them as evidence, not as a template. Work out the question from the whole paper: what the setup assumes, what the experiments are built to test, and what was unclear before the work. If the paper does state its motivating question explicitly (in the abstract or anywhere else), and it is the question the work was set up to answer rather than a framing of the contribution, use it. Then express it the way the authors would have said it at the start, with results, coined names and method details removed (rules 1–4 and 6).
6. **No technical specifics worked out during the work.** No math notation, LaTeX, equations, complexity terms (e.g. "O(n log n) memory"), formal properties of the final solution, experimental protocols (splits, metrics, evaluation setups), or names of the specific baselines and benchmarks the paper compares against. These are things the authors arrived at while answering the question. The only exception is a named, pre-existing artifact that the question itself is *about* (e.g. "How robust is model X to Y?").
7. **Not generic.** The question must be specific to the thinking behind *this* paper. A question that would fit many papers in the area equally well ("How can we make LLMs more efficient?") is too vague. Say what in particular the authors wanted to know, about what, and what made it an open question for them.
8. **One question, not a menu.** Commit to the question you believe the authors were asking. Do not hedge between alternatives ("either … or …, depending on …") unless the authors themselves were explicitly weighing competing explanations.

**The conversation test.** Imagine you are sitting with one of the authors at the start of the project and ask: "What is the research question you are pursuing?" They answer in their own words, the way researchers talk about a problem they are working on: what bothers them, what is unclear, and what they want to find out. Write *that* answer. Anything they would only mention when explaining *how* they solved it, *how* they evaluated it, or *what* they ended up finding does not belong in it.

**Where to look for the question.** Explicit questions in the paper ("we ask whether…", "a natural question is…", "it is unclear whether…"), stated hypotheses, the gap or limitation the introduction builds up to, the problem setup and assumptions of the method or theory sections, and what the experiments are actually designed to test. The design of the experiments often reveals the question more honestly than the paper's framing does. Use these sources to *understand* the question, then write it as the authors would have said it at the start of the work (rule 5).

---

# 1. Form of the answer

## Primary question

- Write a short passage: **a few sentences of context, followed by the question itself**, ending with a question mark. The context says what situation or gap the authors were looking at and why it was an open problem *for them* (not a summary of the paper's background or related-work section, rule 5). The question says what they wanted to find out.
- There is no word limit. Use as many words as the question needs and no more. Every sentence must pass the conversation test (§0): background that the authors would not mention when stating their question does not belong in it.
- Write in plain prose. No bullet points, no headings, no LaTeX, no citations, no references to sections, figures or tables of the paper.
- Write from the point of view of the authors before the work, in the present tense ("Is it possible to…", "We want to understand whether…", "How can … when …?"). Do not refer to "the paper", "this work" or "the authors".
- The question may contain more than one closely related part if that is how the authors framed their single question (e.g. "Can X be done, and how well does it hold up under Y?"). Clearly distinct questions go in the secondary list instead.

## Secondary questions

- A **secondary** question is listed only if the authors clearly pursued a *distinct* question with its own kind of answer (e.g. a method paper that also sets out to explain why existing methods fail; a benchmark paper that also asks how well current models do on it). List them in order of importance.
- Supporting experiments, ablations, sanity checks, side analyses that serve the primary question, and requirements on the primary question ("…while also being efficient") are **not** secondary questions.
- A restatement or sharpening of the primary question is not a secondary question.
- **At most 2 secondary questions.** An empty list is a normal answer. Add one only if the paper would make no sense without it.
- Each secondary question is one or two sentences, ends with a question mark, needs no separate background, and follows every rule in §0.

---

# 2. Procedure (follow these steps in order)

**Step 1. Read the whole paper** and identify what the work was set up to find out (§0, "Where to look").

**Step 2. Work backwards from the answer to the question.** Separate what the paper *found* or *built* (results, the named method, design details, the contribution list) from what the authors *wanted to know*. Ask: before any of this existed, what was unclear to them, and what were they trying to find out?

**Step 3. Decide the primary question** (the one the whole paper is organized around, the one the authors would name first) and any secondary questions (§1).

**Step 4. Write the primary question** in your own words, as the authors would have said it at the start of the project (§1). Then write the secondary questions, if any.

**Step 5. Self-check before answering.** For the primary and every secondary question:
- Does it contain a result, a success claim, or a phrasing that presupposes the answer? Remove it.
- Does it contain a name the paper coins, a design detail of the final solution, math notation, a complexity term, an evaluation protocol, or a specific baseline or benchmark name? Remove or rewrite it.
- Is it just the paper's summary of its contributions (from the abstract, introduction or conclusion) turned into a question? If so, go back to Step 2.
- Does it list the paper's contributions? Replace the list with the question they answer.
- Does every sentence pass the conversation test? Remove what does not.
- Is it specific to this paper rather than generic to the area?
- Is each secondary question distinct from the primary, not a supporting experiment or a restatement? Are there at most 2?

---

# 3. Output format

Return **exactly one JSON object** and nothing else: no markdown code fences, no explanation before or after. Use exactly these keys in this order:

{
  "primary_question": "string: a few sentences of context followed by the question",
  "secondary_questions": ["string"]
}

`secondary_questions` is a list of 0 to 2 strings; use `[]` when there is none.

---

# 4. The paper

<paper>
{{PAPER_TEX}}
</paper>

Recover the primary research question the authors were pursuing when they started this work, and any secondary research questions, phrased the way they would have framed them while doing the work rather than as they appear in the paper. Follow the rules in §0 and the procedure in §2, and return only the JSON object.
