import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";
import { config } from "../config/config.js";
import { login } from "../helpers/auth.js";
import { uploadFile } from "../helpers/files.js";

const mixedLatency = new Trend("mixed_latency", true);
const mixedErrorRate = new Rate("mixed_error_rate");
const readRequests = new Counter("mixed_read_requests");
const writeRequests = new Counter("mixed_write_requests");

export const options = {
  scenarios: {
    mixed_load: config.scenarios.mixed_load,
  },
  thresholds: {
    mixed_latency: [`p(95)<${config.slo.mixedP95Ms}`],
    mixed_error_rate: ["rate<0.05"],
  },
};

export default function () {
  const { cookies, accessToken } = login();
  if (!accessToken) {
    mixedErrorRate.add(1);
    return;
  }

  const token = cookies.access_token[0].value;
  const isWrite = Math.random() < 0.2;

  if (isWrite) {
    writeRequests.add(1);
    const start = Date.now();
    const resp = uploadFile(
      cookies,
      { data: "M".repeat(10 * 1024), mime: "text/plain", name: "mixed.txt" },
      `mixed_${__VU}_${__ITER}.txt`,
    );
    mixedLatency.add(Date.now() - start);
    if (!check(resp, { "mixed write status is 200": (r) => r.status === 200 })) {
      mixedErrorRate.add(1);
    }
  } else {
    readRequests.add(1);
    const start = Date.now();
    const resp = http.get(`${config.baseUrl}/api/list`, { headers: { Cookie: `access_token=${token}` } });
    mixedLatency.add(Date.now() - start);
    if (!check(resp, { "mixed read status is 200": (r) => r.status === 200 })) {
      mixedErrorRate.add(1);
    }
  }

  sleep(0.1);
}

export function handleSummary(data) {
  return {
    "load-test-results/mixed-load-summary.json": JSON.stringify(data, null, 2),
  };
}
