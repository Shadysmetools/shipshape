// k6 load profile template (ramp / soak / spike) with p95 / p99 / error-rate thresholds.
// Run through scripts/load_test.py --engine k6, which checks the host allow-list first.
// Never point this at production or a third-party host.
import http from 'k6/http';
import { check, sleep } from 'k6';

const URL = __ENV.TARGET_URL;
const SCALE = Number(__ENV.SCALE || 1);
const s = (n) => Math.max(1, Math.round(n * SCALE));
const PROFILES = {
  ramp: [{ duration: `${s(30)}s`, target: s(20) }, { duration: `${s(30)}s`, target: s(20) }, { duration: `${s(10)}s`, target: 0 }],
  soak: [{ duration: `${s(10)}s`, target: s(10) }, { duration: `${s(300)}s`, target: s(10) }],
  spike: [{ duration: `${s(10)}s`, target: s(5) }, { duration: '2s', target: s(50) }, { duration: `${s(15)}s`, target: s(50) }, { duration: `${s(10)}s`, target: s(5) }],
  smoke: [{ duration: `${s(5)}s`, target: 2 }],
};

export const options = {
  stages: PROFILES[__ENV.PROFILE || 'ramp'],
  thresholds: {
    http_req_duration: [`p(95)<${__ENV.P95 || 500}`, `p(99)<${__ENV.P99 || 1000}`],
    http_req_failed: [`rate<${__ENV.MAX_ERR || 0.01}`],
  },
};

export default function () {
  const res = http.get(URL);
  check(res, { 'status is 2xx/3xx': (r) => r.status < 400 });
  sleep(0.2);
}
