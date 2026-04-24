import http from "k6/http";
import { check, sleep } from "k6";
import { config } from "../config/config.js";
import { login, getCookieHeader } from "../helpers/auth.js";
import { errorRate, scenarioLatency, recordCheck } from "../helpers/metrics.js";

export const options = {
  scenarios: {
    api_load: config.scenarios.api_load,
  },
  thresholds: {
    http_req_duration: [`p(95)<${config.slo.apiListP95Ms}`],
    http_req_failed: config.thresholds.http_req_failed,
    checks: config.thresholds.checks,
    error_rate: ["rate<0.05"],
  },
};

export default function () {
  const auth = login();
  const headers = getCookieHeader(auth.cookies);
  if (!auth.accessToken) {
    errorRate.add(1);
    return;
  }

  const start = Date.now();
  const response = http.get(`${config.baseUrl}/api/list`, { headers });
  scenarioLatency.add(Date.now() - start);

  const ok = check(response, {
    "api/list status is 200": (r) => r.status === 200,
  });
  recordCheck(ok);
  if (!ok) {
    errorRate.add(1);
  }
  sleep(0.1);
}

export function handleSummary(data) {
  return {
    "load-test-results/api-load-summary.json": JSON.stringify(data, null, 2),
  };
}
