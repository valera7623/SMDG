import { Trend, Rate } from "k6/metrics";
import { config } from "../config/config.js";
import { login } from "../helpers/auth.js";

const authLatency = new Trend("auth_latency", true);
const authErrorRate = new Rate("auth_error_rate");

export const options = {
  scenarios: {
    auth_load: config.scenarios.auth_load,
  },
  thresholds: {
    auth_latency: [`p(95)<${config.slo.authP95Ms}`],
    auth_error_rate: ["rate<0.01"],
  },
};

export default function () {
  const start = Date.now();
  const { accessToken } = login();
  authLatency.add(Date.now() - start);
  if (!accessToken) {
    authErrorRate.add(1);
  }
}

export function handleSummary(data) {
  return {
    "load-test-results/auth-load-summary.json": JSON.stringify(data, null, 2),
  };
}
