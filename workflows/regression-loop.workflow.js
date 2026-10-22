export const meta = {
  name: 'shipshape-regression-loop',
  description: 'ShipShape regression loop: run rounds until the goal is met or a stop condition holds, refuting each new failure',
  whenToUse: 'Re-test after fixes until green or stopped. Args: {pluginRoot, run, maxRounds}',
  phases: [
    { title: 'Round', detail: 'qa_loop.py round (two passes per plan)' },
    { title: 'Refute', detail: 'verify + refute each new failure' },
  ],
}

const A = args || {}
const ROOT = A.pluginRoot
if (!ROOT) throw new Error('pass args.pluginRoot')
const T = 'smetools-agent-kit:'
const PY = `python "${ROOT}/scripts`
const STATUS = { type: 'object', properties: { stop: { type: 'boolean' }, next: { type: 'string' }, reason: { type: 'string' }, last: { type: 'string' }, open_bugs: { type: 'array', items: { type: 'string' } } }, required: ['stop', 'next'] }
const VERDICT = { type: 'object', properties: { verdict: { type: 'string', enum: ['survives', 'refuted', 'inconclusive'] }, why: { type: 'string' } }, required: ['verdict', 'why'] }

const max = A.maxRounds || 3
let s = null
for (let i = 0; i < max; i++) {
  phase('Round')
  s = await agent(`Run ${PY}/qa_loop.py" status ${A.run ? `--run ${A.run}` : ''}. If next is run-round, run ${PY}/qa_loop.py" round --passes 2 --narrate (timeout 30 min) and then status again. Return the final status JSON fields.`, { agentType: T + 'qa-automation-tester', schema: STATUS, label: `round ${i + 1}` })
  log(`round ${i + 1}: ${s.last || ''} -> next ${s.next}${s.reason ? ' (' + s.reason + ')' : ''}`)
  if (s.stop || s.next === 'wait-fix' || s.next === 'file-bugs') break
  if (s.next === 'verify-refute') {
    phase('Refute')
    const suspects = (s.open_bugs || []).filter(b => b.endsWith(':suspected')).map(b => b.split(':')[0])
    await pipeline(suspects, id => agent(`Refute suspected bug ${id} from the ledger (${PY}/qa_loop.py" status). Reproduce on your own path, then record ${PY}/qa_loop.py" bug --id ${id} --status verified|refuted --note "<why>".`, { agentType: T + 'qa-refuter', schema: VERDICT, label: `refute ${id}`, phase: 'Refute' }))
  }
}
return s
