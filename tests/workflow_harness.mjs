// Dry-run a ShipShape workflow script with mocked agents: checks it parses, the phases
// match meta, every agent call names a real plugin agent, and the control flow completes.
// Usage: node tests/workflow_harness.mjs <workflow.js> '<args json>'
import fs from 'node:fs'
import path from 'node:path'

const [file, argsJson] = process.argv.slice(2)
const src = fs.readFileSync(file, 'utf8')
const root = path.resolve(path.dirname(file), '..')
const agentsDir = path.join(root, 'agents')
const known = new Set(fs.readdirSync(agentsDir).map(f => 'smetools-agent-kit:' + f.replace(/\.md$/, '')))
const body = src.replace('export const meta =', 'const meta =') + '\n'
const calls = [], phases = [], logs = []

function fake(schema, prompt) {
  if (!schema) return 'ok: ' + prompt.slice(0, 40)
  const p = schema.properties || {}
  if (p.verdict && p.verdict.enum) return { verdict: prompt.includes('B1') ? 'survives' : 'refuted', why: 'mock' }
  if (p.verdict) return { verdict: 'approve', summary: 'mock review', findings: [] }
  if (p.failures) return { run: 'qa-runs/mock', summary: '1 pass / 1 fail (2 total)', next: 'verify-refute',
    failures: [{ id: 'B1', case: 'TC-02', title: 'welcome text', evidence: 'x.png' }] }
  if (p.stop) return { stop: calls.length > 3, next: calls.length > 3 ? 'stop' : 'verify-refute', last: '1 pass / 1 fail', open_bugs: ['B1:suspected'] }
  if (p.scenes) return { scenes: [{ title: 'Open', label: 'LIVE', lines: ['Open the app.'] }] }
  return {}
}

const agent = async (prompt, opts = {}) => {
  if (opts.agentType && !known.has(opts.agentType)) throw new Error('unknown agentType ' + opts.agentType)
  calls.push({ prompt, agentType: opts.agentType || null, phase: opts.phase || phases[phases.length - 1] })
  return fake(opts.schema, prompt)
}
const parallel = async thunks => Promise.all(thunks.map(t => t().catch(() => null)))
const pipeline = async (items, ...stages) => Promise.all(items.map(async (item, i) => {
  let r = item
  for (const s of stages) r = await s(r, item, i)
  return r
}))
const phase = t => phases.push(t)
const log = m => logs.push(m)
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', body + '\n;')
const metaTitles = (src.match(/title: '([^']+)'/g) || []).map(s => s.slice(8, -1))
const result = await run(agent, parallel, pipeline, phase, log, JSON.parse(argsJson || '{}'), { total: null, spent: () => 0, remaining: () => Infinity })
const unknownPhases = phases.filter(p => !metaTitles.includes(p))
console.log(JSON.stringify({ ok: unknownPhases.length === 0, phases, unknownPhases, agentCalls: calls.length,
  agentTypes: [...new Set(calls.map(c => c.agentType).filter(Boolean))], logs, result }))
