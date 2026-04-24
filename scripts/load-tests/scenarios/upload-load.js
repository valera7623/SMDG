import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";
import { config } from "../config/config.js";
import { login } from "../helpers/auth.js";
import { uploadFile, buildFile } from "../helpers/files.js";

const uploadLatency = new Trend("upload_latency", true);
const uploadErrorRate = new Rate("upload_error_rate");

export const options = {
  scenarios: {
    upload_load: config.scenarios.upload_load,
  },
  thresholds: {
    upload_latency: [`p(95)<${config.slo.uploadP95Ms}`],
    upload_error_rate: ["rate<0.05"],
    http_req_failed: ["rate<0.02"],
  },
};

const file = buildFile("1mb");

export default function () {
  const { cookies, accessToken } = login();
  if (!accessToken) {
    uploadErrorRate.add(1);
    return;
  }

  const start = Date.now();
  const response = uploadFile(cookies, file, `load_${__VU}_${__ITER}.bin`);
  uploadLatency.add(Date.now() - start);

  const ok = check(response, {
    "upload status is 200": (r) => r.status === 200,
  });
  if (!ok) {
    uploadErrorRate.add(1);
  }

  sleep(0.2);
}

export function handleSummary(data) {
  return {
    "load-test-results/upload-load-summary.json": JSON.stringify(data, null, 2),
  };
}
