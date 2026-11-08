# Eval validation for the Baltic marketing pipeline

Date: 5 November 2026. Code: `phase2_step7_v2.py` (`evals_node`),
`phase3/app.py`. Status: current — this document describes the gate as it
runs today, after the fixes of 5 November 2026.

## 1. What the gate is for

The eval gate is the only thing between a draft and publish — and it is not
the last word. A run that passes all checks still pauses at `approve` and
publishes nothing until a human says yes. A run that fails twice ends
unpublished, even though a deck file may exist in `outputs/`.

Two design rules:

1. **Code checks, never self-judgement.** The evals are deterministic Python
   checks (regex, string matching, reading the built file back). The writer
   model never judges its own draft, and no model judges the deck.
2. **The gate checks the built artifact, not the plan.** Since 5 November
   2026 the graph runs writer → deck → evals, so the evals read the actual
   `.pptx` file from disk (`_deck_slide_bodies`). A deck that cannot be read
   fails loudly instead of passing silently.

## 2. Where the gate sits

```
START → planner → researcher → writer → deck → evals
                                              ├─ pass ─────────→ approve ─→ publish / rejected
                                              ├─ fail, < 2 attempts ─→ writer (rewrite, deck rebuilds)
                                              └─ fail, ≥ 2 attempts ─→ END (unpublished)
```

Statuses: `eval_passed`, `eval_retry` (after attempt 1), `eval_failed`
(after attempt 2 — the run ends). The retry loop rewrites the draft; the
deck rebuilds from the new draft on the way back through. Feedback for the
rewrite is the list of failed checks in plain language (`eval_feedback`).

## 3. The 9 checks

| # | Check | What it validates | How it is checked | Pass condition |
|---|-------|-------------------|-------------------|----------------|
| 1 | `citations_present` | The draft actually cites sources. | At least one `[n]` in the draft. | ≥ 1 citation |
| 2 | `citations_valid` | Citations point at real research docs, not invented numbers. | Every cited `[n]` satisfies 1 ≤ n ≤ number of brand docs retrieved. | All cited numbers in range |
| 3 | `all_docs_cited` | No research doc is ignored. | Set of cited numbers equals 1..n_docs. | Every doc cited |
| 4 | `sources_section` | The draft names its sources for the human reviewer. | The word "sources" appears in the draft. | Present |
| 5 | `banned_claims_zero` | No marketing hype that was explicitly banned. | None of `guaranteed roi`, `no risk`, `best-in-class`, `unlimited` appears (case-insensitive). The writer is also blocked on these at write time and raises if one slips through. | Zero matches |
| 6 | `pii_zero` | No personal data leaks into a draft. | No regex match for email-like, phone-like (`ddd-ddd-dddd`), or IBAN-like patterns. | Zero matches |
| 7 | `draft_length_ok` | The draft is a real draft, not a stub. | Draft length ≥ 200 characters (the writer also raises below 200). | ≥ 200 chars |
| 8 | `citation_coverage_ge_0_5` | Claims are cited, not just the first sentence. | Share of long sentences (> 40 chars) that carry a `[n]`; e.g. run-608c83c6 scored 0.778, run-6fbd9d40 scored 0.938. | Coverage ≥ 0.5 |
| 9 | `deck_slides_distinct` | **The deck differs slide to slide.** Added 5 Nov 2026 from Siva's finding: every content slide repeated the same three doc snippets and the old gate still passed, because it only ever looked at the draft. | The built `.pptx` is opened and the body text of each content slide (title slide and closing slide skipped) is compared. **Title text is excluded on purpose** — titles always differ, so including them would let identical bodies pass. | At least 1 body read, and all bodies different |

Checks 1–8 look at the draft. Check 9 looks at the built deck. All 9 must pass.

## 4. How each check was itself validated

A check that has never been seen to fail is not a check — it is a decoration.
What was actually tested:

- **Check 9, first version, was wrong.** It read whole slides including
  titles, so identical bodies passed. It was caught by testing against a
  known-bad artifact: all 4 old decks (with identical content slides)
  correctly FAILED only after `_deck_slide_bodies` was fixed to exclude the
  title shape. Lesson recorded in the runbook: test a new check against a
  known-bad artifact before trusting it.
- **Check 9, live negative case.** Run-9a8b0e77 (5 Nov 2026) passed 8/9 and
  failed `deck_slides_distinct` twice — the retry loop rewrote the draft
  twice and the same failure recurred, because the cause was in the
  paragraph-matching code, not the draft. The run ended `eval_failed` and
  unpublished, exactly as designed. The cause was then fixed (section-based
  assignment, see §6) and the same draft rebuilt clean: all 4 slides got
  their own paragraph, zero fallback slides.
- **The gate reads the file, not the plan.** `_deck_slide_bodies` opens the
  `.pptx` on disk. If the file cannot be read it returns `[]` and check 9
  fails instead of crashing the run.
- **Coverage is honest about what it measures.** It counts cited sentences,
  not whether the draft stayed on brief. Run-3a8128e5 (held-out 1) drifted
  wider than its brief (it added RAG/LangGraph and Power BI to an Embedded
  Linux brief) and still passed at 0.68 — the gate checks citations and
  safety, not brief scope. That drift was reported to Siva before approval,
  not hidden by the gate.

## 5. Evidence — runs against the gate

All runs on a local RTX 3060 desktop (Ollama qwen3:14b / qwen3:8b, bge-m3), 0 SEK.

| Run | Topic | Coverage | Attempts | Result |
|-----|-------|----------|----------|--------|
| run-42f19498 | Phase 3 crash-resume gate | — | 1 | Passed, published |
| run-3a8128e5 | Held-out 1, manufacturing | 0.68 | 1 | Passed, published (draft drifted wider than brief — reported before approval) |
| run-6a477f78 | Held-out 2, public sector | 0.90 | 1 | Passed, published |
| run-4998b8ae | Manufacturing re-run | 0.80 | 1 | Passed, published |
| run-9df798c8 | Held-out 3, energy | 0.955 | 1 | Passed, published |
| run-8dab4d14 | Energy re-run | 0.955 | 1 | Passed, published |
| run-8961f443 | Retail verification (9-check gate) | 0.758 | 1 | Passed, paused at approve |
| run-f0e02246 | Power BI / Power Apps | 0.882 | 1 | Passed, paused at approve |
| run-e47d732d | Power BI / Power Apps | 0.875 | 1 | Passed, paused at approve |
| run-9a8b0e77 | Power BI / Power Apps | 0.867 | 2 | **Failed** (`deck_slides_distinct`), ended unpublished |
| run-608c83c6 | Power BI / Power Apps | 0.778 | 1 | Passed, approved, published |
| run-6fbd9d40 | Power BI / Power Apps | 0.938 | 1 | Passed, approved, published |

Totals at 5 Nov ~10:44: 12 decks built, 8 published locally.

## 6. Known limits — what the gate does NOT catch

- **Same idea in different words.** Check 9 catches identical text, not
  repeated claims. Slides 3 and 5 of run-e47d732d both talked about
  containers/Kubernetes/Docker in different words and passed. That is the
  writer's job: writer rule 9 ("NO REPEATED CLAIMS — each paragraph a
  different point") covers it, and the planner's short-headline rule plus
  section-based deck assignment keep each slide on its own section.
- **Brief scope.** See §4: the gate does not check that the draft stayed
  inside the brief. A human reviewer still has to read the draft.
- **PII and banned phrases are pattern lists.** The PII check is three
  regexes (email, phone, IBAN shapes); the banned list is four fixed
  phrases. A novel leak phrasing would not be caught. The human approval
  step is the backstop.
- **Citation coverage is a share, not a proof.** A sentence can carry a
  citation to the wrong doc and still count. Checks 2 and 3 bound the
  numbers, but only a human reading the draft can judge whether a citation
  supports the sentence it follows.

## 7. How to re-validate

From the lab folder (venv `.venv`):

```bash
# Read a run's evals from its checkpoint
.venv/bin/python -c "
import json, phase2_step7_v2 as s
v = s.app.get_state({'configurable': {'thread_id': 'run-608c83c6'}}).values
print(json.dumps(v.get('evals'), indent=1))
print('fallback slides:', v.get('deck_fallback_slides'))
"

# Rebuild a run's deck from its checkpoint and check slide bodies
.venv/bin/python -c "
import phase2_step7_v2 as s
st = s.app.get_state({'configurable': {'thread_id': 'run-9a8b0e77'}}).values
out = s.deck_node(st)
bodies = s._deck_slide_bodies(out['deck_path'])
print('slides:', out['deck_slides'], 'fallback:', out['deck_fallback_slides'],
      'distinct:', len(bodies) >= 1 and len(set(bodies)) == len(bodies))
"

# Render a deck and look at it (the appearance checks are human, not code)
soffice --headless --convert-to pdf --outdir /tmp/render deck-run-608c83c6.pptx
pdftoppm -png -r 60 /tmp/render/deck-run-608c83c6.pdf /tmp/render/slide
```

## 8. Change log

- **31 Oct 2026:** 8 checks, graph order writer → evals → deck. The deck was
  built after evals, so no deck check was possible.
- **5 Nov 2026 ~10:00:** 9th check added (`deck_slides_distinct`); graph
  reordered writer → deck → evals → approve; first version of the check
  read titles too and was fixed the same morning (see §4).
- **5 Nov 2026 ~10:20:** deck appearance fixes (titles 28pt, no repeated
  Audience line, body 14pt) — appearance is judged by a human rendering the
  deck, not by the gate.
- **5 Nov 2026 ~10:30:** planner must write short headlines (≤ 45 chars);
  writer rule 9 (no repeated claims); body paragraphs no longer cut at 280
  chars.
- **5 Nov 2026 ~10:37:** section-based deck assignment (`_draft_sections`):
  each `##` section goes to the slide its heading matches best. This fixed
  the run-9a8b0e77 failure, where keyword-only matching misfiled paragraphs.
- **5 Nov 2026 ~10:31:** planner service-name normalisation (a split
  "Power BI" / "Power Apps" maps to the combined "Power BI / Power Apps"
  entry); the API returns the failure reason (HTTP 422) instead of a bare
  "Internal Server Error".
