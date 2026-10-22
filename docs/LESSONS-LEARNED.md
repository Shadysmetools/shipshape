# ShipShape: lessons learned

What months of real agent sessions taught us about autonomous QA, evidence, delivery and safety. Every lesson is generic: no client, person, URL, key or ID is named. The format is always **symptom → root cause → fix/guardrail**.

The companion file `LESSONS-TO-BEHAVIOUR.md` turns each lesson ID below into a concrete kit default, check, hook or retry. Lessons marked **[P0]** are the 15 that change the kit's behaviour most.

## How this was mined

- **Sources:** every Claude Code transcript on the source machine (main sessions plus every `subagents/` and `workflows/` transcript), the job and session scratchpad reports (READMEs and `*.md`), the managers' board, the failure playbooks, the agent operating strategy, and two team learning logs.
- **Coverage:** 39 project folders, of which 30 hold transcripts. The main pass streamed 3,188 JSONL transcripts (about 5.4 GB) and **1,034,256 lines**; a final recount found 3,196 (639 main, 1,797 subagent, 760 workflow), because live sessions kept adding files. Lines over 400 KB were counted but not parsed. The 758 small workflow state files (`.json`, about 1.7 MB) were not scanned.
- **Documents:** 1,331 scratchpad and manager documents were read in the first pass, a count that includes READMEs of third-party repositories cloned into scratchpads. The targeted passes excluded those clones.
- **Method:** a streaming Python pass. It parsed each line, kept assistant and user text, split it into paragraphs and kept those that matched a theme and a lesson signal ("root cause", "turned out", "never", "guardrail" and so on). That gave 11,083 candidate paragraphs. Targeted passes per theme followed, and every lesson was cross-checked against the written team learning logs.
- **Lessons from mechanics, not incidents:** TS-02 (negative hours), OD-05 (case-sensitive branches) and BR-07's background-tab half have no recorded incident in the corpus. They are written from how the tools work, because the kit must still guard them.
- **Caveat:** regex presence over-counts. Sessions that hunt for a string also quote it. Rankings are judgement checked against the written logs, not raw counts.

---

## 1. QA and testing (QA)

**QA-01 [P0] "Done" claims without live evidence.** About 1 in 12 "done / fixed / passing" claims was contradicted within three turns, by the human or by a background task. The claim was made from the diff or a unit test, not from the deployed surface. Guard: no done-claim without machine evidence from the live surface (screenshot, network capture, command output, video). Without it, the wording is "pushed, unverified".

**QA-02 [P0] "All green" that wasn't.** Reports said "all green" or "suite green" while a separate status gate was red, or before the run had finished. In one case the claim reached the baton file and a later commit had to correct it. Summaries were written from memory, not from the finished run's output. Guard: report "N pass / M fail / K blocked / J not checked" taken from the full list, and only after the run has ended and been read.

**QA-03 [P0] Two-agent bar: verify, then refute.** Fixes that passed CI and the author's tests were killed by an adversarial refuter several times: a fail-open the mocked tests hid, tests that asserted the buggy behaviour, and a leak the hardening patch itself introduced. CI proves the tests pass, not that the tests are right. Guard: before anything is filed or shipped, an independent verifier confirms it and a fresh refuter, on its own path, tries to kill it. The verdict quotes check counts.

**QA-04 [P0] Tests that pass for the wrong reason.** Several tests stayed green after the behaviour they guarded was removed. Causes included fake sessions that skipped the guarded path, a query reorder that sent a "member" test down the "owner" path, and a timeout test that only proved the stdlib default. Guard: a revert proof, where reverting the fix (or removing each guard one at a time) must turn the named test red for the right reason, with the assertion line recorded.

**QA-05 Mutation tools that silently test nothing.** A mutation script reported every mutant "KILLED" while every run was actually erroring: it copied only part of the tree, so fixtures were missing. Its text anchors had also rotted after fixes, so half the mutants never applied. Guard: run a baseline with no mutant first and refuse to report if the baseline is not green. Count "anchor missing" as a failure, and re-run the whole tool after every fix round.

**QA-06 "Flaky" called from one run.** Failures were labelled flaky after a single run, yet a rerun of the same configuration showed one "flaky" file failing every time. The real causes were load-related cold-start timeouts, fixed sleeps and Windows line-ending differences, not randomness. Guard: call a test flaky only after several recorded reruns of the same config, run gate suites one after another, and wait with poll-until-deadline instead of fixed sleeps.

**QA-07 [P0] Empty or zero results trusted without a control.** Scans returned "0 errors" because the tool was missing from PATH, and a sandboxed interpreter printed nothing at all. An anonymous storage listing returned 0 items, and only a privileged control on the same prefix showed it was a real block. Guard: every scan, search or count carries a positive control, a query that must return something. A zero without a passing control is "unknown", not "clean".

**QA-08 Mocks that differ from the real provider.** A mock that was stricter than the real API (it rejected unknown fields with an error, while the real one silently dropped them) hid a silent data-loss class. Mock behaviours marked "assumed" produced passes and fails that proved nothing. Guard: every mock behaviour is tagged verified or assumed. Tests that rest on assumed behaviour are labelled as such and re-run against a real sandbox.

**QA-09 Test fixtures that hide mix-ups.** Fakes where the record ID equalled the human reference passed every test while production showed internal IDs to users. Guard: fixtures use deliberately different values for every pair of fields that can be confused (ID and reference, sender and receiver, business date and wall date).

**QA-10 Warm-stack reruns that pass without doing anything.** A rerun matched the previous run's message (same reference) and passed without sending anything new. Guard: snapshot message or row IDs before acting, use a fresh event version per run, and assert on new items only.

**QA-11 Test-environment confound graded as a product failure.** A language test failed because the test account's own preferences forced a language. Account memory also leaked unrelated real projects into the test. Guard: run behaviour and language tests on a clean, dedicated test profile. Check account preferences and memory before grading, and re-grade confounded results as "not testable".

**QA-12 Half-checked multi-item issues.** An issue with five items was graded on one item; the others were never checked. Guard: grade every item of a multi-item issue, or list each ungraded item as "not checked".

**QA-13 [P0] Shared stacks killed mid-run by another agent.** Another session's restart of a shared local stack turned 60+ scenarios red, and code landing mid-run made a 90-minute result a mixture of two versions. The lock in place only polled a file with no queue, so waiters starved for hours. Guard: a queued lock for shared stacks, ports and browser profiles. Stamp the git HEAD at the start and end of each scenario, and re-run reds alone on the final tip before reporting.

**QA-14 Harness rows that vanish silently.** A new component was never started because the harness started a hard-coded list, so its row simply disappeared from the report: no SKIP, no FAIL. Guard: the report compares the expected row set with the produced one. A missing row is a failure.

**QA-15 Stale "fixed" verdicts.** Sixteen days after an investigation, 4 of 19 "fixed" verdicts were false: the "fixed" line already existed at the baseline commit, and three metrics were worse. Guard: test a "fixed" claim against the baseline SHA, and re-verify every open finding after any gap.

**QA-16 A walkthrough failure is not a product bug until the data says so.** Two of three walkthrough "bugs" came from the recorder: a verdict string that always said "delivered", and an expectation that contradicted the design. Guard: before filing, read the database or the API state behind the failing step.

**QA-17 Local-only passes.** Tests passed only with a local option, or only because an ignored local folder existed. A blanket ignore rule also left a module's own data folder uncommitted while every local layer stayed green. Guard: run the branch proof from a clean detached worktree of the branch. State the boundary of the proof in the same sentence.

**QA-18 Clocks in tests.** A test pinned to a calendar date next to "now + 14 days" broke for every agent on one day. A settable clock left moved by one scenario made later scenarios fail only in a full run. Guard: never pin real dates. Split time reads into business time (settable) and liveness time (wall clock), and restore the clock after every scenario that moves it.

**QA-19 Stale status documents quoted as truth.** A status table said an issue was closed while it was open in UAT. Guard: status comes from the live tracker at the time of reporting, never from a saved summary.

## 2. Browser automation (BR)

**BR-01 The automation browser hijacking the owner's browser.** An automation server attached to the owner's real browser intercepted file pickers and moved windows "by itself". A signed-in personal profile was also signed out by a test. Guard: automation runs in its own profile or browser. Before driving, check whether another automation session is already attached, and never sign out of or into the owner's profile.

**BR-02 One browser per session.** Parallel agents that shared a single automation browser stepped on each other. Guard: browser work in one session runs in sequence, or each agent gets its own isolated context under the shared-resource lock.

**BR-03 A shared profile carries old state.** A shared automation profile was still signed into an earlier throwaway account, and its global local-storage flags would have false-failed a fresh-account test. Guard: each test persona gets a fresh browser context. Clear or isolate storage, and record which identity each run used.

**BR-04 Signed-out sessions produce no evidence.** Runs ended without screenshots because the automation browser was never signed in. Guard: a preflight confirms the expected identity is signed in before the plan starts. If it is not, stop as BLOCKED with the reason; do not run blind.

**BR-05 Init scripts that do not fire.** A masking script registered as an init script did not run on persistent profiles, and a CSS blur missed the page's real DOM. The video then showed what it should have hidden. Guard: apply masks after load, verify them on the rendered page, and run a post-render sanitise pass on the video before any upload.

**BR-06 Recordings scaled down by default.** The recorder shrank videos to a default box unless the recording size was set equal to the viewport, so the output was upscaled and blurry. Guard: set the recording size equal to the viewport and record one context per run.

**BR-07 Background tabs and second tabs.** Single-session web apps (chat clients and the like) show "open in another window" in every tab once a second tab exists. Background tabs throttle rendering, so captures come out stale or blank. Guard: one tab per app, bring the page to the front and wait for a visible, settled state before every capture, and screenshot only the region under test.

**BR-08 Passkeys, OTP, captcha and payment are owner-only.** Some logins need a passkey or an SMS code sent to a real person's phone; each retry pinged that person. Guard: the agent stops and waits whenever a password, passkey, OTP, captcha, payment page or terms page appears. Never retry a login that notifies a human.

**BR-09 Rate limits and retry classes.** A 403 matched neither branch of a "429 or 5xx" retry loop, so nothing was retried while the stored message claimed "after internal retries"; elsewhere 400s were retried forever, and one API key shared by every feature hit its quota and silently dropped work. Error classes and quotas were never designed, only assumed. Guard: retry only 429, 5xx and network errors (backoff, jitter, `Retry-After`), never 400/403/404, give heavy features their own key or budget, and log every dropped item.

**BR-10 Tool limits and outages.** The browser tool could not resize, press keys or run scripts in some setups, and whole tool servers went down mid-session. Guard: a capability preflight per run. When a capability is missing, fall back to a local headless script on a copy of the profile with every write request blocked, and say so in the report.

**BR-11 Desktop and remote control need real events.** Synthetic text did not reach a remote desktop, and a modifier tap used to grab focus was forwarded and opened menus. Guard: use low-level key events, avoid modifier taps for focus, and screenshot after every action and check it before the next.

**BR-12 Test from the link the user actually got.** Progress never synced for a real user because the link he received lacked a key parameter the tester's browser already had. Guard: test with the exact link or invite that was sent, in a clean browser.

**BR-13 Loopback-only testing misses the edge.** A component that only ever talked to a local fake was blocked in production by the CDN's browser check, because its HTTP library sent a non-browser user agent. Guard: one end-to-end probe through the real edge (CDN, tunnel, proxy) before calling an integration done.

## 3. Video and narration (VID)

**VID-01 TTS that hangs or writes empty files.** The TTS engine sometimes hung forever on one clip and left a 0-byte audio file, which later runs reused from the cache. Guard: a timeout around every synthesis call, a few tries, cache only non-empty files that decode, and regenerate any cached clip that fails to read.

**VID-02 Self-healing caches.** A short network drop corrupted one cached clip, and every later recording run crashed until someone noticed. Guard: validate each cached asset before use and rebuild it automatically, rather than crash.

**VID-03 ffmpeg concat needs identical streams.** Concatenating with stream copy drifted or dropped audio when segments differed in frame rate, size, pixel format or audio layout, and title cards had no audio track at all. Guard: normalise every segment (same fps, size, `yuv420p`, 48 kHz stereo) and give silent cards a generated silent track before concatenating.

**VID-04 Subtitles and drawtext on Windows paths.** Filter-graph escaping of drive-letter paths and `%` characters broke burned-in captions. Guard: render captions into HTML slides and record those, or pass caption text through a file with expansion off and the font copied into the working directory.

**VID-05 Large uploads time out.** A 17 MB video upload to a chat bot timed out at 600 s and succeeded at 2,400 s, and network drops interrupted others. Guard: re-encode to a delivery size (for example 1024 px wide) before sending, scale the timeout with file size, and retry network failures.

**VID-06 Size, caption and length limits.** Video sends failed or were cut because a chat bot caps uploads (50 MB), video captions (1,024 characters) and messages, and long pass/fail captions went over. The sender treated a video, its caption and its text as one unit. Guard: check size per channel and compress once before sending (falling back to a document or a hosted link), put a short caption on the video, and send the full text as a reply split under the message limit.

**VID-07 Privacy slips in frames.** A first evidence video showed a real client's brand names, and its upload stayed as an orphan in a public bucket. Another frame showed a personal chat window. Text scans never see pixels. Guard: run a privacy pass on video and screenshots before upload (masking plus a human or model look at sampled frames), and track every upload so orphans can be removed.

**VID-08 Synthetic voices matched to real people.** Narrated videos uploaded to a speaker-recognition product were auto-tagged with a real person's name, because the TTS voice scored above the auto-naming threshold. Guard: label synthetic-voice uploads, and turn off speaker auto-naming for evidence uploads.

**VID-09 Narration pacing.** Scenes that held long after the voice ended felt broken. Guard: end each scene a fixed short beat (about half a second) after its narration audio ends.

**VID-10 Several clocks on one screen.** One story showed three apps in three time zones, which made "within N seconds" claims unreadable. Guard: captions state one time zone (UTC from the server) and check timing claims against the provider's own timestamps.

**VID-11 Encoding in narration scripts.** Windows PowerShell 5.1 read narration text as ANSI and garbled it. Only English voices were installed, so another language silently fell back to English. Guard: read and write narration text as UTF-8 explicitly. A preflight lists the installed voices and fails loudly when the requested language has none.

**VID-12 Agents given too much media stall.** One agent given about 94 full-resolution frames stalled and was killed by the watchdog. Guard: split media analysis into batches of about 30 frames per agent.

**VID-13 Evidence decays.** Signed frame URLs expired after about 15 minutes, and server logs rotated after about a week. Guard: download evidence the moment it is found, and keep the run's artefacts with the report.

## 4. Delivery and alerts (DL)

**DL-01 [P0] Chat-bot network timeouts.** Sends to a chat bot failed on transient Windows network timeouts; a plain retry went through. Guard: every outbound send retries network errors and 5xx with backoff, with a per-attempt timeout scaled to payload size.

**DL-02 Retries that double-send.** A retry of a multi-step delivery (video, then text, then report) resent the steps that had already succeeded. A crash part-way through a batch wrote duplicate memos, because the "seen" cursor was written once at the end. Guard: record each successful step (message ID) and skip it on retry. Advance the cursor per item, in the same transaction as the work.

**DL-03 One bad message blocks every later alert.** A watcher aborted the whole batch on one malformed message (a lone surrogate character) and never advanced its cursor, so it re-failed forever. Guard: per-item error handling. Quarantine the bad item, log it and advance.

**DL-04 Dedupe-then-work in separate commits loses events.** Writing the dedupe row, then doing the work as a separate commit, turned any failure in between into permanent loss: the provider's redelivery was swallowed by the dedupe key. Guard: the dedupe row and its work commit together, or not at all.

**DL-05 [P0] Duplicate alerts from more than one watcher.** Each alert was forwarded several times because re-arming a watcher started a new instance without stopping the older ones, and a TTL-based "alert once" was not once after a restart. Nothing enforced a single watcher per stream. Guard: a singleton watcher per alert stream (a lock or PID file that the new instance checks and the old one honours), plus a persistent dedupe store keyed on the alert's content hash.

**DL-06 One owner per figure.** Two sessions sent different numbers for the same metric to the same client channel. Guard: each figure has one owning seat. Others quote it, never recompute it, and nothing is sent until it is final.

**DL-07 Reply threading.** A message sent as a threaded reply to a manager's bot was never acknowledged, while plain sends to the same bot always were. The receiving bot only reacted to some message shapes, and the sender assumed "sent" meant "received". Guard: thread replies where the receiver handles them, treat an acknowledgement (or delivery status) as the proof, and resend as a plain message when none arrives in time.

**DL-08 "Dry run" flags that do not cover every command.** A messaging tool's dry-run flag applied to one subcommand only; the send command ignored it and really sent. Guard: test that every dry-run path performs zero network calls, and preview outbound text yourself before any real send.

**DL-09 Asynchronous failure.** Some messaging APIs answer HTTP 200 and report the real failure later through a status webhook, so tests that ignored status callbacks passed on messages that never arrived. Guard: a send counts as delivered only after the delivered status arrives. Tests listen for failure callbacks.

**DL-10 Know the channel's limits before promising.** An agent promised to clean up old posts, then found the bot could not delete messages older than about 48 hours and the human account had no delete rights. The limit was never checked before the promise. Guard: state cleanup limits up front, and prefer not sending over planning to delete later.

**DL-11 Secrets never go to a group.** Personal keyed links were nearly sent to a group chat, because the delivery script had one default destination for everything. Guard: personal links and credentials go only by direct message to the person, never to shared channels.

**DL-12 Silent waits get killed.** Agents that waited silently on long jobs were killed by the watchdog. A background job writes nothing to its output file until it finishes. Guard: run long jobs in the background with a heartbeat. Treat an empty output file from a running job as "still running", never as "failed" or "no results".

## 5. Security and privacy (SEC)

**SEC-01 [P0] Agents printing secrets.** Agents and subagents printed live API keys, a database password, session tokens and a bot token into transcripts, often "only to list the field names". The redaction regexes were wrong (for example `\b` does not match before `secret` inside `client_secret`), and agents read whole secret files to inspect them. Guard: never `cat` a secrets file; read it in code and print only booleans and field names, test redaction against real key shapes, and rotate anything printed.

**SEC-02 Secrets in tool inputs, not outputs.** About 70% of secret occurrences were inside command lines the agent composed. Redacting tool output cannot catch those. Guard: inject secrets as environment variables the agent never sees, and block commands that contain literal key shapes.

**SEC-03 Secrets persist in every store.** Transcripts, the prompt history file and job scratch folders all held credentials long after use; one sweep covered transcripts but missed the job folders. Guard: secret sweeps cover every agent store (transcripts, history, scratchpads, shell snapshots) and report counts only.

**SEC-04 Publishing evidence is an outward act.** An unconfirmed evidence upload stayed public in a bucket. Security evidence with a public link would have revealed the very exposure being fixed. Guard: a public link needs the owner's direct OK for that workstream. Security work never gets public links: use privacy-filtered screenshots and counts only.

**SEC-05 [P0] Client live sites and production data.** Test details typed into a client's live checkout or forms create real records and alert real staff, and client production data copied into evidence stores leaks customer details. Both happen because a live site looks just like a test site to an agent. Guard: test accounts and test data only, stop at payment pages, never submit to a client's live site without the owner's OK, and keep raw extracts in git-ignored folders with documents carrying aggregates only.

**SEC-06 Mask at the sink.** A masking rule placed at one call site leaked through every other writer of the same log, and missed the URL-encoded spelling of the same token. Guard: mask in the logging sink itself, and match both raw and decoded forms.

**SEC-07 Text scans do not cover images.** A "scan clean" result covered dozens of screenshots and video frames no tool had looked at. Guard: list every image the scan skipped. Inspect them (by eye or model) or name them as not inspected.

**SEC-08 Real names in test data.** A real first name was used as a test teammate and appeared in public evidence. Guard: use only obvious placeholder personas ("Test Teammate") and placeholder domains.

**SEC-09 Auth headers kept across redirects.** Python's urllib followed a redirect to another host and kept the Authorization header. Guard: authenticated senders refuse cross-host redirects.

**SEC-10 Loopback trust behind proxies.** "No password means loopback only" became wide open behind a reverse proxy or tunnel, where every caller looks local. A server-side link-preview feature also fetched any URL a user typed, loopback included. Guard: never trust the client address. Refuse to start without auth outside test mode, and turn off server-side URL fetchers on exposed test stacks.

**SEC-11 Path and URL checks bypassed by encoding.** A deny list on the raw path was bypassed with percent-encoding, and a URL validator and the HTTP client parsed the same string differently. Guard: decode and canonicalise once, refuse leftover `%`, and validate with the same parser the client uses.

**SEC-12 Large-file leak scans.** A leak scan that walked vendored dependency folders never finished, while the real risk sat in large data exports. Guard: skip vendored and third-party trees, but always stream large data files.

## 6. Timesheets (TS)

**TS-01 Estimates are not measurements.** A first timesheet estimated from commit history said 40 h; the session logs measured about 24 h for the same period. Guard: measure from session transcript timestamps, keep the measuring script next to the output, and state the method in the file.

**TS-02 [P0] Unsorted timestamps give negative hours.** Transcript lines are not guaranteed to be in time order, and merged main and subagent streams interleave. Differencing unsorted stamps gives negative or inflated gaps. Guard: sort every stamp list before computing gaps, assert that no interval is negative, and fail the run if one is.

**TS-03 Overlapping sessions double count.** Main sessions and their subagents run at the same time; summing them counts the same hour twice. Guard: take the union of active intervals across all streams, never the sum.

**TS-04 One idle-gap rule everywhere.** Two projects used different break rules (10 vs 20 minutes) and their totals could not be compared; the client received inconsistent numbers. Guard: one gap rule, stated in a Method sheet, used across all projects and changed only by an explicit, dated decision.

**TS-05 Machine turns inflate human activity.** Background-agent notifications look like user turns: about 35% of apparent "user" turns in one measurement were agent output. Prompts queued into an idle session also look like work. Guard: exclude task notifications, wrappers and queued prompts from activity stamps.

**TS-06 Evidence per hour.** Clients questioned hours that had no trail. Guard: every timesheet line links to a work block (start, end, the request typed, the commits made), with phone numbers masked and a key scan before sharing. Blocks with no clear project signal are not billed, and the total of unbilled hours is stated.

**TS-07 Values, not formulas, in client spreadsheets.** Spreadsheets opened from a chat app start in protected view, which does not calculate formulas, so totals showed blank. Guard: write computed values into client files.

**TS-08 Check visibility before importing.** The importing account could see only one employee, and that employee belonged to another company, so an import "for the developer" would have landed on the wrong record. Guard: before any import, read which employees, companies and projects the account can see. Import by database IDs, and confirm employee and company visibility with the owner.

## 7. Odoo and Odoo.sh (OD)

**OD-01 [P0] Staging copies of production can send live.** A staging copy of production carries real customer contacts, and after go-live every new copy would also inherit "integration enabled" plus the production endpoint and secret. Guard: every module that sends ships a `data/neutralize.sql` that pauses sending on neutralised copies. A fresh install defaults to staging mode with sending off and an empty allow-list. Sending also checks an environment marker, and a hand-restored backup is treated as production until proven otherwise.

**OD-02 `noupdate` and cron state.** Once a cron record sits under `noupdate`, later XML edits never apply on upgrade. The hosting platform also restores cron active flags after each deploy, so turning a cron off was not a kill switch. Guard: keep logic in Python, and make kill switches a system parameter, never the cron's active flag.

**OD-03 Build URLs change on every push.** Every push to a staging branch made a new build with a new URL, and a partner's test hit a dead link. Guard: during a partner test, freeze the staging branch, push to a dev branch only, and always tell the partner which link is current.

**OD-04 Dropped builds restart from a fresh production copy.** When a staging build was dropped, the next push built from a fresh production copy, not the old staging data, and new modules were not installed. Guard: after any rebuild, re-check installed modules, safety switches and test data before testing.

**OD-05 Branch names must match exactly.** Git hosts and the build platform treat branch names as case-sensitive, while Windows file systems do not, so a branch that differs only in case can look present locally and missing remotely. Guard: resolve branch names with `git ls-remote` against the exact remote name before pushing or promoting.

**OD-06 Full-repo test builds and record rules.** Full-repository dev builds crashed on unrelated custom fields, and the default admin user hit record rules other users never see. Guard: test a named list of modules, and test with staging-only users that copy real groups.

**OD-07 RPC calls that fail after committing.** Some XML-RPC methods return `None`, which the protocol cannot marshal, so the call raised an error after the write had already committed. A blind retry would apply it twice. Guard: tolerate only that specific error, re-read the state, and never blindly retry writes.

**OD-08 RPC payloads that hang.** Task creation hung forever on HTML entities and some tags in descriptions, and a PowerShell REST client deadlocked on large bodies. Guard: sanitise text to plain UTF-8 and simple tags before writing, use a proper HTTP client, and put a timeout on every RPC.

**OD-09 Built-in webhooks are fire-and-forget.** The platform's "send webhook" action makes one POST with a 1 s timeout, never retries, and fires before commit, so it loses real events and sends rolled-back ones. Guard: use an outbox table written in the same transaction, drained by a retrying worker.

**OD-10 Daily crons drift across DST.** A daily cron at a fixed local hour drifted by an hour after a DST change, because the interval is added without time-zone normalisation. Guard: compute the next run in the target time zone, and test across the DST date.

**OD-11 Stored fields show now, not history.** A stored computed "accepted" flag reflected the current state, and "date of order" was rewritten by tooling. Guard: read history from tracking records, and store your own first-event timestamps.

**OD-12 Odoo writes need explicit approval.** A relayed "approved" nearly triggered a delete that the owner later cancelled, because the writing session trusted a peer's summary of the owner's words. Guard: every write to a client database needs the owner's explicit OK in the same conversation, naming the records and values.

## 8. Production promotions (PR)

**PR-01 [P0] One promotion at a time, with a watch.** Promotions merged 28–33 minutes apart broke the 60-minute post-deploy watch twice, so an incident could not be pinned to one change. Guard: promotions merge one at a time. Each gets a read-only production replay of what it changes, then a 60-minute watch, and the next merges only after a clean watch. Batch fixes into fewer promotions rather than one per fix.

**PR-02 Rollback first.** Irreversible migrations (a DROP) shipped without a down file, and risky switches were coupled to code. Guard: write and test the rollback before the merge. Ship backward-compatible code first and flip the irreversible switch last, behind a one-command rollback.

**PR-03 Deploys that were never verified.** Many production deploys had no verification entry at all, and a deploy CLI failed once and worked on retry. Guard: after every deploy, fetch the live page or health endpoint, check that the new build identifier is present, and record the result.

**PR-04 Fixes stranded on staging.** Ten bugs stayed live in production while their fixes sat merged on staging, and green promotions skipped them. Guard: each promotion starts from a list of staging fixes not yet in production, and states which it includes and why the others wait.

**PR-05 Removing a feature is a product decision.** A long-unpromoted change that removed a feature looked like a stuck fix. Guard: route promotions that delete behaviour to the owner as a question, not into a fix wave.

**PR-06 Size the blast radius on real data.** A feared mass breakage measured at 3 live links; another fear measured at 0. Guard: before choosing "fix before release" or "follow-up", count the affected rows in production with a read-only query.

**PR-07 Forward-only promotions leave old data wrong.** Promoting a fixed scorer changed nothing visible, because thousands of stored verdicts kept their old values. Guard: every promotion that changes stored derivations states its backfill plan, or explicitly that there is none.

**PR-08 Switches left on after a stalled run.** A stalled live test left sending enabled for 25 hours on a database with real phone numbers. Guard: before resuming any live test, read every safety switch and count rows outside the test scope. Re-pause straight after the last send, not at the end of the session.

**PR-09 Only the approver promotes.** Cards drifted toward "done" on the strength of "we're working on it" messages, and agents were tempted to move their own work to production. When status is self-reported, nobody checks it. Guard: only the named approver moves work to production or closes an issue, and status comes from code evidence (branch, PR, deploy record).

## 9. Windows-specific gotchas (WIN)

**WIN-01 cp1252 stdout crashes Python.** Piped Python output crashed with `UnicodeEncodeError: 'charmap'` on emoji and Arabic, which killed whole analysis runs. Guard: set `PYTHONIOENCODING=utf-8` (or reconfigure stdout to UTF-8) in every launcher, and open every text file with an explicit encoding.

**WIN-02 [P0] BOMs and invisible characters in values.** A production payment flow failed on every request because a price-ID environment variable began with an invisible BOM (U+FEFF); the secret key itself was fine, and the API only said the ID did not exist. Windows tools and copy-paste add BOMs and zero-width characters that no one can see in a dashboard. Guard: strip BOM, zero-width characters and surrounding whitespace when loading secrets and config, validate key shapes (prefix and length) at startup, and read config files as `utf-8-sig`.

**WIN-03 PowerShell 5.1 encodings.** PowerShell 5.1 reads files as ANSI by default, `Set-Content` writes the ANSI codepage, and `Out-File` writes UTF-8 with a BOM. Guard: always pass `-Encoding utf8` (or use .NET `ReadAllText(path, UTF8)`), and prefer Python for file writes that other tools read.

**WIN-04 PATH differences and exit 127.** A process started detached through PowerShell inherited a PATH without Git Bash, so a module test "failed" in 0.03 s with "'bash' is not recognized"; search tools missing from PATH returned 0 results silently, and a CLI self-update briefly made the binary unknown. Each launcher builds its own PATH, so the same command works in one shell and not another. Guard: a doctor step resolves absolute paths for every tool, exit 127 or "not recognized" is reported as an environment failure (never a test result), and it is retried once after a pause.

**WIN-05 Line endings.** `core.autocrlf=true` checks files out with CRLF. Exact-string edits then missed, editors silently rewrote files to the other ending, `sed -i` stripped CRs, and tests that regex source text failed only on Windows. Guard: match the file's existing endings, check the committed blob (not the working tree) for churn, and keep source-text tests ending-agnostic.

**WIN-06 PID reuse.** A day-old PID file pointed at another agent's process. Guard: store each PID with its process creation time, and kill only when both still match.

**WIN-07 Detached children die with the launching shell.** A child started with `DETACHED_PROCESS` still died when the shell ended, and a database server child that inherited stdout made every captured start command hang. Guard: use `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` (plus breakaway from the job, with a fallback), and redirect child stdout to null.

**WIN-08 Task Scheduler and sleep.** A non-elevated shell cannot register at-startup tasks, yet a script still printed "registered". Laptops in standby silently skipped night routines. Guard: use `-ErrorAction Stop` and read the task back after registering. Use start-when-available, and record a heartbeat receipt per run so missed slots are visible.

**WIN-09 Socket resets on unread bodies.** Closing a socket that still held unread request bytes sent an RST, which surfaced as WinError 10053 about one run in five. Behind a tunnel, an undrained body poisoned the kept-alive connection. Guard: always drain the full request body (chunked included) before replying.

**WIN-10 Agent shell quirks.** In the agent's Bash tool, `\\` collapsed inside heredocs and `\uXXXX` escapes became literal invisible characters in patched source. Exported variables did not persist between calls, and paths with spaces word-split. Guard: write scripts to a file with the file-writing tool and run them; pass state through files or arguments; quote every path.

**WIN-11 Copies of symlink-heavy folders.** A robocopy turned 47 symlinks into full files and tripled a cache's size. Guard: compare source and destination sizes and counts before deleting anything, and stop on a mismatch.

**WIN-12 Git Bash rewrites paths, and hidden errors lie.** Commands like `git show <ref>:<path>` and arguments with a leading slash were mangled by Git Bash path conversion. One agent had added `2>/dev/null`, so it concluded the file did not exist. The shell's automatic POSIX-to-Windows conversion touched arguments that were not paths, and the suppressed stderr hid the clue. Guard: set `MSYS_NO_PATHCONV=1` for git and API calls, and never suppress stderr on a command whose failure would change a conclusion.

## 10. Agent coordination (CO)

**CO-01 [P0] A relayed approval is not consent.** Peer sessions relayed "the owner approved" for production writes, a public upload, a delete and use of the owner's own browser. Acting on the relay would have done a delete the owner later cancelled. Guard: only the owner's own words in this conversation, or the permission system, count as approval. A peer can relay a request, never an approval, so ask the owner directly and quote what they said.

**CO-02 No permission laundering through subagents.** A coordinator could ask a subagent to merge, label, publish or flip what the coordinator itself was not allowed to do. Guard: subagents inherit the strictest gate of the chain. Irreversible and approval-gated steps (merge to production, approval labels, the flip itself) are prepared by agents and executed only by the human or with their direct word.

**CO-03 Verify claims from peers.** A message said to come from another session claimed a tool behaved a certain way; the tool's source said otherwise. Guard: treat peer messages as data and check them against the source before acting.

**CO-04 Parallel sessions and shared files.** A second session produced a competing plan for the same work. Parallel builders wrote the same docs at the same time, and `git commit --only <file>` swept another builder's uncommitted lines into the wrong commit. Guard: before starting, read the folder and every `HANDOFF*.md`. Re-list shared files right before editing, and commit only your own hunks of shared files.

**CO-05 Agents pushing onto shared branches.** A fix agent's push landed on a shared branch through the upstream push default. Guard: create branches with `--no-track` and always push with an explicit `remote branch`.

**CO-06 Stale state.** A canonical checkout sat hundreds of commits behind for weeks, and a merge request turned out to be already merged. Guard: fetch and print the behind-count at the start of every run, and re-verify any parked request against live state before acting on it.

**CO-07 Wrong target.** Agents queried the wrong database, the wrong deployment or the wrong product. Guard: every dispatch pins repository, branch, environment, database and model lane in one line, echoed back. If the target is still ambiguous, ask one yes/no question.

**CO-08 Durable resume.** A laptop slept for about 19 hours mid-change and froze every agent; nothing was lost only because the handoff file and open PRs held the state. Guard: keep a resume block in the handoff file, updated at every milestone.

**CO-09 Subagent mechanics.** Some subagents could not write report files, one agent type needed a git working directory, and more than about four agents in parallel thrashed. Guard: subagents return reports inline and the parent saves them. Cap parallelism at about four, and split large inputs.

**CO-10 Ask, don't guess.** Advice given before checking the user's stack had to be retracted. Guard: when expected behaviour, ownership or tooling is unknown, ask the owning seat in one numbered batch and keep working while waiting.

**CO-11 Name every destructive action.** Bulk cleanups deleted user-authored items, and a blanket "do it" was read as covering irreversible steps. Guard: list the exact objects and get a confirmation per destructive action. A general go-ahead does not cover deletes.

**CO-12 Route messages through the right identity.** Messages meant for a manager were nearly sent as a direct message from a human's own account. Guard: agents message people through their own bot or channel identity, never by impersonating a human, and only the decisions that belong to an escalation owner (money, legal) go to that owner.

**CO-13 Measure agent self-reports cleanly.** A naive correction-rate measurement read about 10–12%, while the true rate was about 3%, because background-agent notifications were counted as human turns. Guard: any KPI that is mined from transcripts filters out agent notifications and wrappers first.
