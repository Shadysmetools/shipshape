# Operating rules (every ShipShape agent follows these)

These come from real QA and integration work: each rule exists because breaking it once cost something.

## 1. Evidence first
- Every test result and every bug gets a **narrated video** (a natural voice explains the steps and where the problem is), screenshots, and a transcript or log. A claim with no evidence is not a result. The report counter turns an evidence-less PASS into BLOCKED.
- Store evidence per run (`qa-runs/<date>-<goal>/round-NN/...`) and keep an index; check the index before uploading so nothing is uploaded twice.
- **Exceptions:**
  - **Security work**: no narrated video and no public link. Privacy-filtered screenshots and read-only probe output (status codes, counts), kept private. Notifiers send the finding count only.
  - **Client production data** never goes into uploads; use synthetic or test-order evidence.
  - **Making evidence public** is an outward publish and needs the owner's direct OK for that workstream.

## 2. Privacy filter before anything leaves the machine
Run `scripts/privacy.py scan` on every folder, video caption file and text you upload or post: no real person or client names, no emails, phones, keys, tokens, passwords or user storage paths. Keep the deny-list of private names OUTSIDE the repo (`SMEKIT_DENYLIST`). In-page masking can miss dynamic text and every screen frame counts: check sample frames, and watch the video before it goes outside.

## 3. Two-agent bar before anything is filed or shipped
An independent **verifier** reproduces the claim on its own path, then a **refuter** tries to kill it (environment confound, flakiness, wrong expectation, stale build). Only survivors are filed. Report "**N pass / M fail**" from the full list; never "all green". Grade every item of a multi-item issue, or list it as NOT CHECKED.

## 4. One pipeline, visible on a board
Backlog → In progress → Staging → **UAT** (re-tested as a real user, on video) → **Approval** → Production. Only the approver moves a card to Production or closes an issue. Status comes from evidence (a branch, a PR, a build log, a run report), not from "we're working on it". Status tables come from the live tracker, never from a stale document.

## 5. Approvals come from the owner, directly
A peer session or agent can relay a request, never an approval. Production writes, money, outward messages, publishing and irreversible actions need the owner's words in this conversation; quote them. When unsure who owns a decision, ask (batch the questions, number them, keep working while you wait).

## 6. Robustness
- A **timeout on every long step** (the scripts enforce them: per step, per run, per round). One unbounded recording once hung for 18 hours.
- Keep turns short; run long jobs in the background; resume from the ledger, not from memory.
- **Self-healing caches**: narration clips are validated before use and regenerated if broken.
- Measure blast radius on real data before calling something a disaster or a non-issue; confirm every "empty" result with a control query.

## 7. Test data only, never pay, stop before input on live sites
- Test accounts and fake data only (`example.com` addresses, `+00 000 000 0000` style numbers). Never type a real person's details.
- **Never pay.** The recorder refuses payment/checkout steps; a human handles any payment page.
- **Client live sites:** stop before any input (forms, sign-ups, bookings) unless the site owner OK'd it in this conversation. Read-only checks are fine.
- Clean up test data you created (or list it for the owner) at the end of a round.

## 8. Learn and graduate
Every role keeps dated KPIs: evidence rate, first-try correctness (claims that survived the refuter), false-positive rate, time to first evidence, stalls, privacy incidents, honest pass/fail counts. A role runs unattended only on proven KPIs and is demoted on a regression.
