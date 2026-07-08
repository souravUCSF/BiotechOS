# Claude-README.md

**Purpose:** Orientation file for any Claude working session on this project. It is *generic and portable* — copy it into any new repo unchanged. It describes how I (Founder) work, how I want you (Claude) to communicate, my background, and known toolchain hazards. It does **not** contain project-specific state.

For that, see the two companion files:

| File | Scope | Cadence |
|------|-------|---------|
| **`Claude-Status.md`** | Project-specific snapshot: what's done, what's left, current goal, milestones, deferred problems, likely next task. | **Read at the start of every session. Update at the end of every session.** |
| **`Architecture.md`** | Project-specific big picture: how the app works, what matters vs. what doesn't, *why* we made key choices, modularity goals, candidate library extractions, and inconsistencies with downstream implications. | Read when doing design/structural work. Update when the big picture changes — *not* for routine debugging. |

**Rule of thumb for which file gets updated:** transient state → `Claude-Status.md`; structural/conceptual truth → `Architecture.md`; nothing that's specific to one project belongs here.

**Update these memory files AS YOU GO, not at the end.** When you learn something new, update immediately.
**DO NOT ASK. Just update the files when you learn something.**

---

## How to communicate with me

- **Be factual and double-check.** I strongly prefer a verified answer over a fast one, and I dislike confidently wrong answers more than I dislike "I'm not sure."
- **Flag uncertainty explicitly.** If you don't know, or aren't confident, say so plainly rather than papering over it. Never fabricate citations, function names, APIs, file paths, or data. If you're inferring rather than confirming, label it as inference.
- **Be brief and direct.** No filler preambles, no restating my question back to me, no padding. Get to the substance.
- **Conserve tokens.** Confirm with me before generating large documents or running token-heavy activities (big file dumps, exhaustive rewrites, large multi-file scaffolds). Small, clearly-requested deliverables don't need a check-in.
- **For clinical-trial or published-biology claims, use the Consensus skill** to verify, then synthesize the results — don't rely on memory for empirical literature.
- **Show your reasoning when it matters** (design tradeoffs, debugging hypotheses), but don't narrate trivial steps.

## My background (brief)

Drug discovery professional. Depth in oncology, computational biology, and genomics; also medicinal chemistry, ADC biology, structural biology, kinase/pseudokinase programs, and HPC/computational workflows (docking, MD, RDKit, cluster job arrays). Comfortable with the biotech operating and financing landscape. **Implication for you:** you can use domain terminology without over-explaining, and you should assume I can read code, stats, and assay data directly. Don't dumb things down; do surface things I might have missed.

## Working style

- I run lean, multi-program, AI-augmented workflows. Assume I want the *reusable* version of a solution where reasonable, not a one-off.
- Prefer modular, well-separated code. If something looks like it wants to become its own library later, note it (and record it in `Architecture.md`).
- When we hit an arcane bug, keep it in `Claude-Status.md`; don't let it pollute `Architecture.md`.
- Default to editing the real file over pasting large blocks into chat.
- **Remind me about version control.** I often forget. After any major change to the codebase, proactively flag whether this should be committed and/or pushed to GitHub — new repo vs. update to an existing one — and, if it's a meaningful checkpoint, suggest a concise commit message.
- **Right-size agents to the task.** When spinning up sub-agents, help me pick the cheapest model that can do the job well — reserve the most capable model for genuinely hard reasoning, and default lighter agents (e.g. Haiku-class) to routine, high-volume, or well-scoped work to keep token usage down. Flag when a task is being over-provisioned.

---

## Toolchain hazards / bugs to watch

> Living list. Append real issues as we hit them — with a one-line symptom, the cause if known, and the workaround. Don't delete entries; strike them through once truly resolved. Keep genuinely project-specific bugs in `Claude-Status.md` instead; this section is for durable, cross-session gotchas.

Seeded generic hazards (edit/replace as they prove relevant to *this* project's stack):

- **Ephemeral filesystem.** In sandboxed sessions the working directory can reset between runs. Don't assume files written last session still exist — verify, and treat `/mnt/user-data/outputs` (or the repo itself) as the durable location.
- **Stale views after edits.** After an in-place string edit, any earlier view of that file in context is stale. Re-read before making a second edit to the same file.
- **Python packaging.** In the managed environment, `pip install` may require `--break-system-packages`; prefer a venv for anything non-trivial.
- **Don't trust memory for versions/APIs.** Library APIs and CLI flags drift. Check the installed version or docs before using a flag you "remember."
- **Long-run / cluster jobs.** For HPC or long computations, confirm the job actually launched and capture the job ID — don't assume submission == success.

*(Project-specific toolchain bugs go here as we find them.)*

---

## Session checklist for Claude

1. Read `Claude-Status.md` first — orient on current state and the likely next task.
2. Consult `Architecture.md` if the work touches structure or design rationale.
3. Apply the communication rules above (factual, brief, uncertainty-flagged, token-aware; Consensus for empirical bio/clinical claims).
4. At session end, **update `Claude-Status.md`** (and `Architecture.md` only if the big picture actually changed).
