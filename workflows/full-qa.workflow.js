export const meta = {
  name: 'shipshape-full-qa',
  description: 'ShipShape full QA: code + security review, automated tests twice, load, live regression, refute, report, dry-run delivery',
  whenToUse: 'A goal-driven QA pass on a local or staging web app with recorded evidence. Args: {goal, pluginRoot, plans, url, allowHosts, base, config, liveUrl, load, lang, rounds}',
  phases: [
    { title: 'Review', detail: 'qa-code-reviewer and qa-security-reviewer in parallel' },
    { title: 'Automated x2', detail: 'every plan runs twice; disagreement = FLAKY' },
    { title: 'Load', detail: 'qa-load-tester on the allow-listed host' },
    { title: 'Live regression', detail: 'read-only flows on staging/live with DevTools evidence' },
    { title: 'Refute', detail: 'qa-refuter on every failure and finding' },
    { title: 'Report', detail: 'offline HTML report + spoken summary' },
    { title: 'Deliver', detail: 'notify.py dry-run to the configured channels' },
  ],
}

const A = args || {}
const ROOT = A.pluginRoot
if (!ROOT) throw new Error('pass args.pluginRoot (the value of ${CLAUDE_PLUGIN_ROOT})')
const PY = `python "${ROOT}/scripts`
const hosts = (A.allowHosts || ['127.0.0.1', 'localhost'])
const hostArgs = hosts.map(h => `--allow-host ${h}`).join(' ')
const plans = (A.plans || []).map(p => `--plan "${p}"`).join(' ')
const T = 'smetools-agent-kit:'
const RULES = 'Rules: test data only, never pay, stop before input on a live site, local/staging hosts only, every long command with a timeout, report N pass / M fail with evidence paths.'

const REVIEW = { type: 'object', properties: { verdict: { type: 'string' }, summary: { type: 'string' }, findings: { type: 'array', items: { type: 'string' } } }, required: ['verdict', 'summary'] }
const STATUS = { type: 'object', properties: { run: { type: 'string' }, summary: { type: 'string' }, next: { type: 'string' }, failures: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, case: { type: 'string' }, title: { type: 'string' }, evidence: { type: 'string' } }, required: ['id', 'case'] } } }, required: ['run', 'summary', 'next'] }
const VERDICT = { type: 'object', properties: { verdict: { type: 'string', enum: ['survives', 'refuted', 'inconclusive'] }, why: { type: 'string' } }, required: ['verdict', 'why'] }

phase('Review')
const [review, security] = await parallel([
  () => agent(`Review the diff ${A.base ? `against ${A.base}` : 'of the current branch against its base'} before QA. Write {"verdict","summary"} to qa-runs/review.json. ${RULES}`, { agentType: T + 'qa-code-reviewer', schema: REVIEW, phase: 'Review' }),
  () => agent(`Security review: run ${PY}/security_scan.py" --repo . ${A.url ? `--url ${A.url} ${hostArgs}` : ''} --out qa-runs/security, then review the diff. Return the count and severities only in summary; details stay in the private file. ${RULES}`, { agentType: T + 'qa-security-reviewer', schema: REVIEW, phase: 'Review' }),
])
log(`review: ${review ? review.verdict : 'skipped'} | security: ${security ? security.summary : 'skipped'}`)

phase('Automated x2')
let status = await agent(`Open or resume the QA ledger and run one round:
1. ${PY}/qa_loop.py" start --goal "${A.goal}" ${plans} --max-rounds ${A.rounds || 3}
2. ${PY}/qa_loop.py" attach --kind security --file qa-runs/security/security.json (if it exists) and --kind review --file qa-runs/review.json (if it exists)
3. ${PY}/qa_loop.py" round --narrate --passes 2   (timeout 30 min)
4. ${PY}/qa_loop.py" status
Return the run dir, the round summary, next, and every open bug (id, case, title, evidence path). ${RULES}`, { agentType: T + 'qa-automation-tester', schema: STATUS })

if (A.load && A.url) {
  phase('Load')
  await agent(`Run ${PY}/load_test.py" --url ${A.url} ${hostArgs} --profile ${A.load} --out ${status.run}/load, then ${PY}/qa_loop.py" attach --run ${status.run} --kind load --file ${status.run}/load/load.json. Return the thresholds line.`, { agentType: T + 'qa-load-tester' })
} else log('load: skipped (no args.load or args.url)')

if (A.liveUrl) {
  phase('Live regression')
  await agent(`Read-only regression on ${A.liveUrl}: run each plan with "live": true via ${PY}/record.py" into ${status.run}/live/, and on any FAIL collect Chrome DevTools console/network evidence. Never type or submit on a live site. ${RULES}`, { agentType: T + 'qa-live-regression-recorder' })
} else log('live regression: skipped (no args.liveUrl)')

phase('Refute')
const failures = (status.failures || [])
if (!failures.length) log('nothing to refute')
const verdicts = await pipeline(failures,
  f => agent(`Independent verify: reproduce failure ${f.case} (${f.title || ''}) yourself from its plan in the ledger at ${status.run}. Evidence: ${f.evidence || 'see ledger'}. Report what you observed.`, { label: `verify ${f.id}`, phase: 'Refute' }),
  (observed, f) => agent(`Try to refute this failure. Claim: ${f.case} fails (${f.title || ''}). The verifier observed: ${observed}. Then record the outcome: ${PY}/qa_loop.py" bug --run ${status.run} --id ${f.id} --status verified|refuted --note "<why>".`, { agentType: T + 'qa-refuter', schema: VERDICT, label: `refute ${f.id}`, phase: 'Refute' }),
)
const survivors = failures.filter((f, i) => verdicts[i] && verdicts[i].verdict === 'survives')
log(`refute: ${survivors.length} of ${failures.length} failure(s) survive and can be filed`)

phase('Report')
const report = await agent(`Run ${PY}/qa_report_html.py" ${status.run} and ${PY}/narrator.py" report ${status.run} --lang ${A.lang || 'en'}, then ${PY}/privacy.py" scan ${status.run}. Return the report path, the summary line from the ledger, and the privacy scan line.`, { label: 'report' })

phase('Deliver')
const delivery = A.config
  ? await agent(`Dry-run delivery only: ${PY}/notify.py" ${status.run} --config ${A.config} --lang ${A.lang || 'en'}. Do NOT add --send. Return what would be sent per channel.`, { label: 'deliver (dry-run)' })
  : 'no config: delivery skipped'

return { run: status.run, summary: status.summary, next: status.next, review: review && review.verdict, security: security && security.summary,
  survivingBugs: survivors.map(f => f.id), report, delivery }
