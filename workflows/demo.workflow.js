export const meta = {
  name: 'shipshape-demo-video',
  description: 'ShipShape demo video: script the scenes, capture them, narrate, check privacy, review',
  whenToUse: 'A polished narrated demo or tutorial of a feature. Args: {feature, pluginRoot, url, allowHosts, lang, out}',
  phases: [
    { title: 'Script', detail: 'audience, goal, 5-9 scenes' },
    { title: 'Capture', detail: 'record the flow or build slides' },
    { title: 'Review', detail: 'privacy scan + an independent viewer check' },
  ],
}

const A = args || {}
const ROOT = A.pluginRoot
if (!ROOT) throw new Error('pass args.pluginRoot')
const T = 'smetools-agent-kit:'
const SCRIPT = { type: 'object', properties: { scenes: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, label: { type: 'string' }, lines: { type: 'array', items: { type: 'string' } } }, required: ['title', 'lines'] } } }, required: ['scenes'] }

phase('Script')
const script = await agent(`Write a demo script for: ${A.feature}. Audience: a non-technical team member. 5 to 9 scenes, one idea each, plain words, each scene labelled LIVE, SIMULATED, REGRESSION or ILLUSTRATION. Fake data only, no names, emails or phones.`, { agentType: T + 'qa-demo-video-producer', schema: SCRIPT })

phase('Capture')
const out = A.out || 'qa-evidence/demo'
const video = await agent(`Produce the video from this script: ${JSON.stringify(script)}.
Use python "${ROOT}/scripts/record.py" with a plan (--narrate) for scenes you can drive in the browser on ${A.url || 'the local app'} (allowed hosts: ${(A.allowHosts || ['127.0.0.1']).join(', ')}), and python "${ROOT}/scripts/slides_video.py" for the rest. Voice language: ${A.lang || 'en'}. Output under ${out}. Return the MP4 path, duration and .srt path.`, { agentType: T + 'qa-demo-video-producer' })

phase('Review')
const [privacy, viewer] = await parallel([
  () => agent(`Run python "${ROOT}/scripts/privacy.py" scan ${out} and report the result line and any hits (locations only).`, { label: 'privacy scan' }),
  () => agent(`You are a first-time viewer. Read the script and the .srt under ${out}. Is every step understandable without prior knowledge? List at most 5 concrete fixes. Script: ${JSON.stringify(script)}`, { label: 'viewer check' }),
])
return { video, privacy, viewer }
