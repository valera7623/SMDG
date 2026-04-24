import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";
import { config } from "../config/config.js";
import { login } from "../helpers/auth.js";

const soakErrors = new Rate("soak_errors");

export const options = {
  scenarios: {
    soak_test: config.scenarios.soak_test,
  },
  thresholds: {
    soak_errors: ["rate==0"],
    http_req_failed: ["rate==0"],
  },
};

export default function () {
  const { cookies, accessToken } = login();
  if (!accessToken) {
    soakErrors.add(1);
    return;
  }

  const response = http.get(`${config.baseUrl}/api/list`, {
    headers: { Cookie: `access_token=${cookies.access_token[0].value}` },
  });
  if (!check(response, { "soak list status is 200": (r) => r.status === 200 })) {
    soakErrors.add(1);
  }

  sleep(1);
}

export function handleSummary(data) {
  return {
    "load-test-results/soak-summary.json": JSON.stringify(data, null, 2),
  };
}
