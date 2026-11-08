# Mock Q&A — Baltic Marketing Graph (Phase 4)

**Purpose:** the questions a hiring manager or a client would ask about this service,
with honest answers. Prepared 5 Nov 2026 from the teaching guide and the learning
journal. Live drill completed 5 Nov 2026, ~11:20 — Siva answered all 12 in his own words;
Q5, Q6, Q11 and Q12 below carry his corrections (9 checks not 8, ~50–60 s runs, a script
can do it but tediously, OOM as the hardest bug).
**Status:** drilled. Nothing here is a claim about a deployed commercial product.

---

## 1. Walk me through the system in one minute

A goal and an audience go in. A planner (qwen3:14b) turns them into a plan using only
Baltic's own services. A researcher retrieves Baltic brand documents and summarises
them. A writer drafts a blog post with a numeric citation on every factual sentence.
Code checks — not the model judging itself — verify citations, banned phrases, and
personal data. If it passes, a deck is built and the graph pauses for a human to approve
or reject. Approval publishes to a local folder only. The whole thing runs as a FastAPI
service in Docker on a local machine, with a SQLite checkpoint so a crash resumes the
run instead of restarting it.

## 2. What happens when the writer produces a bad draft?

The evals node fails it and sends feedback back to the writer — up to two attempts.
After two failures the graph ends with no deck. A failed gate is never carried forward,
and nothing reaches the human approval step until it passes.

## 3. Who decides what gets published?

A human, always. The graph pauses at an interrupt and waits for a yes or no with the
same run identity. There is no auto-approve path in the code, and "published" means a
copy in a local `published/` folder — there is no external publish path at all.

## 4. What happens if the container dies mid-run?

The checkpoint survives. Proven 4 Nov 2026: a run paused at approve, the container was
killed and started again, and the same run was still there — deck ready, approval still
pending. Approving after the restart published it. The checkpoint lives in `step7.db`
on the host (bind mount), not only inside the container.

## 5. How do you know the evals work?

Held-out evals, 4–5 Nov 2026: five fresh topics the graph had never seen — manufacturing,
public sector, energy, retail, and Power BI / Power Apps. All passed all 9 code checks on
the first attempt (citation coverage 0.68, 0.90, 0.955, 0.758, 0.778–0.938). All were
approved by a human and published locally. Cost: 0 SEK, about a minute of model time each.
And the gate is proven by failure, not just passes: run-9a8b0e77 failed the
deck-distinctness check twice and ended unpublished. Human visual inspection is the
backstop — the identical-slides and title-overlap faults this morning were found by a
human eye, not by the code.

## 6. What does it cost to run?

Nothing in money — local models (qwen3:14b, qwen3:8b, bge-m3) on a local GPU box.
Cost is tracked as tokens and seconds: a typical run is ~50–60 seconds of model time.
That is a property of this exercise, not a production cost model.

## 7. Why local models instead of frontier APIs?

Three reasons, all deliberate: cost (0 SEK per run), privacy (Baltic's documents never
leave the machine), and the point of the exercise — proving the deployment pattern
(checkpoints, interrupts, crash-resume) works with the cheapest model that passes, so
the pattern is not tied to any one provider.

## 8. How do you stop it making things up?

Three layers. The researcher only summarises retrieved brand documents, and says so
when a document does not cover a point. The writer may only use that research, with a
citation on every factual sentence. And the evals are code checks: citations must be
present, valid, and cover all research docs; banned phrases and personal-data patterns
fail the draft outright. Nothing in the chain asks the model whether its own work is good.

## 9. What can't it do? (Say this first — it is the honest answer.)

It is a learning exercise, not a production system. It cannot publish anywhere real.
It has no authentication, no multi-user handling, and no metrics database — the
in-memory run counter resets on every restart, and the runbook says so plainly. Its
evals check citations and safety, not whether the draft stuck to the brief: the
manufacturing held-out run passed all checks while covering services outside its brief.
And it runs on one local machine that sleeps overnight.

## 10. What would you change for production?

Persistent metrics in a table instead of an in-memory counter. Authentication on the
API. A brief-scope check in the evals, since the citation checks do not cover that.
A queue so long runs do not block the request. And the model choice re-evaluated per
task — local models for this exercise, frontier models where the quality bar needs them,
with the evals as the gate either way.

## 11. Why LangGraph instead of a plain script?

Because the hard parts are state, pauses, and resumes. A plain script can do it — it
would just have to re-implement checkpoints, interrupts, conditional routing, retries
and run history in one very big script. LangGraph gives you that as the framework's job,
with the state machine visible in the graph definition instead of hidden in flags and
files. A new step is a new node, not a rewrite.

## 12. What was the hardest bug, and what did it teach you?

Siva's pick: the OOM errors. The planner kept failing with an HTTP 500 that looked like
a server fault — Ollama had defaulted to a 40k context and the 14b model plus its KV cache
blew past the 12 GB card with Windows holding ~2.5 GB. The diagnosis came from reading the
server error body and nvidia-smi, not from the symptom. Fix: num_ctx 2048 — and a reboot
does not fix an OOM. Lesson: infra bugs lie about their symptoms; measure before blaming
the code. Two more, from the build: the checkpoint package missing from the Docker image
(the venv had it, Docker did not — verify inside the container, not just on the host),
and wiping the lab folder with `rm -rf *` in the wrong directory (the workspace copy is
the master; copy-back at the end of each session turns a wipe into a shrug).

---

*Keep everything, for revise and teach others. Do not delete the lab contents.*
