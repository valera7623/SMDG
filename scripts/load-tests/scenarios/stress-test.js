import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";
import { config } from "../config/config.js";
import { login } from "../helpers/auth.js";

const stressErrorRate = new Rate("stress_error_rate");
const authLatency = new Trend("auth_latency", true);

export const options = {
  scenarios: {
    stress_test: {
      executor: "ramping-arrival-rate",
      startRate: Number(__ENV.STRESS_START_RPS || 50),
      timeUnit: "1s",
      preAllocatedVUs: Number(__ENV.STRESS_PREALLOCATED_VUS || 100),
      maxVUs: Number(__ENV.STRESS_MAX_VUS || 2500),
      stages: [
        { duration: "2m", target: 200 },
        { duration: "5m", target: 500 },
        { duration: "2m", target: 1000 },
        { duration: "2m", target: 1500 },
        { duration: "1m", target: 0 },
      ],
    },
  },
  thresholds: {
    auth_latency: [`p(95)<${config.slo.authP95Ms}`],
    stress_error_rate: ["rate<0.05"],
  },
};

export default function () {
  const start = Date.now();
  const auth = login();
  authLatency.add(Date.now() - start);
  if (!auth.accessToken) {
    stressErrorRate.add(1);
    return;
  }

  const listResp = http.get(`${config.baseUrl}/api/list`, {
    headers: { Cookie: `access_token=${auth.cookies.access_token[0].value}` },
  });
  if (!check(listResp, { "stress list status is 200": (r) => r.status === 200 })) {
    stressErrorRate.add(1);
  }
  sleep(0.05);
}

export function handleSummary(data) {
  return {
    "load-test-results/stress-test-summary.json": JSON.stringify(data, null, 2),
  };
}
