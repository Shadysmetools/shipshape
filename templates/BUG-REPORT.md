# [QA] <short, specific title: what breaks, where>

**Filed only after the two-agent bar:** verified by an independent agent: <yes, how> · refuter tried to kill it: <what it tried, why it failed>

## In plain words
<One or two sentences a non-technical reader understands: who is affected and what they cannot do.>

## Steps to reproduce (test data only)
1. <step>
2. <step>

## Expected vs actual
- **Expected:** <quote the spec/ticket line, or say it is an assumption>
- **Actual:** <what happened>

## Evidence
- Narrated video: <link> (timestamp mm:ss where it breaks)
- Screenshot(s): <link>
- Console / network (Chrome DevTools): <errors, failing request + status>
- Trace: <trace.zip>

## Environment
Build/commit <sha>, URL <staging>, browser <name + version>, account <test account role>, language <EN/AR>.

## Root cause (if known)
<file:line and why; or "not investigated">

## Severity and impact
P<1-4> · <how many users / which flow>

Labels: `found-by:<agent|person>` `method:<automated|live-regression|review>` `area:<area>`
Privacy check: no real names, emails, phones, keys or client data in this issue or its attachments.
