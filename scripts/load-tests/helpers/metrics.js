import { Counter, Rate, Trend } from "k6/metrics";

export const errorRate = new Rate("error_rate");
export const scenarioLatency = new Trend("scenario_latency", true);
export const successfulChecks = new Counter("successful_checks");
export const failedChecks = new Counter("failed_checks");

export function recordCheck(ok) {
  if (ok) {
    successfulChecks.add(1);
    return;
  }
  failedChecks.add(1);
  errorRate.add(1);
}
