import http from "k6/http";
import { check, fail } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";
import { config } from "../config/config.js";

const authLatency = new Trend("auth_latency", true);
const authErrorRate = new Rate("auth_error_rate");
const authPolicy429Rate = new Rate("auth_policy_429_rate");
const authSuccessRate = new Rate("auth_success_rate");
const authTimeoutRate = new Rate("auth_timeout_rate");
const authEofRate = new Rate("auth_eof_rate");
const auth429Count = new Counter("auth_429_count");
const auth401Count = new Counter("auth_401_count");
const authTimeoutCount = new Counter("auth_timeout_count");
const authEofCount = new Counter("auth_eof_count");
const auth400Count = new Counter("auth_400_count");
const auth403Count = new Counter("auth_403_count");
const auth500Count = new Counter("auth_500_count");
const auth502Count = new Counter("auth_502_count");
const auth503Count = new Counter("auth_503_count");
const auth504Count = new Counter("auth_504_count");
const auth5xxCount = new Counter("auth_5xx_count");
const authOtherStatusCount = new Counter("auth_other_status_count");
const authMissingCookieCount = new Counter("auth_missing_cookie_count");
const authMode = (__ENV.AUTH_TEST_MODE || "capacity").toLowerCase(); // capacity | policy
const failFastWindowMs = Number(__ENV.AUTH_FAIL_FAST_WINDOW_SECONDS || 20) * 1000;
const failFastMinSamples = Number(__ENV.AUTH_FAIL_FAST_MIN_SAMPLES || 20);
const failFast401Ratio = Number(__ENV.AUTH_FAIL_FAST_401_RATIO || 0.9);
const failFastEnabled = String(__ENV.AUTH_FAIL_FAST_ENABLED || "true").toLowerCase() !== "false";

const testStartedAt = Date.now();
let failFastSamples = 0;
let failFast401 = 0;

export const options = {
  scenarios: {
    auth_load: config.scenarios.auth_load,
  },
  thresholds: {
    auth_latency: [`p(95)<${config.slo.authP95Ms}`],
    auth_error_rate: authMode === "policy" ? ["rate<0.05"] : ["rate<0.01"],
    auth_success_rate: authMode === "policy" ? ["rate>0.2"] : ["rate>0.95"],
    auth_policy_429_rate: authMode === "policy" ? ["rate>0.2"] : ["rate>=0"],
    auth_timeout_rate: ["rate<0.01"],
    auth_eof_rate: ["rate<0.01"],
  },
};

export default function () {
  const username = __ENV.ADMIN_USER || config.adminUser;
  const password = __ENV.ADMIN_PASSWORD || config.adminPassword;
  const payload = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`;
  const url = `${config.baseUrl}/api/auth/login`;
  const start = Date.now();
  const response = http.post(url, payload, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    timeout: __ENV.AUTH_REQUEST_TIMEOUT || "60s",
  });
  authLatency.add(Date.now() - start);

  const responseError = String(response?.error || "").toLowerCase();
  const isTimeout = responseError.includes("timeout");
  const isEof = responseError.includes("eof");

  if (isTimeout) {
    authTimeoutRate.add(1);
    authTimeoutCount.add(1);
  } else {
    authTimeoutRate.add(0);
  }

  if (isEof) {
    authEofRate.add(1);
    authEofCount.add(1);
  } else {
    authEofRate.add(0);
  }

  if (response?.status === 429) {
    authPolicy429Rate.add(1);
    auth429Count.add(1);
    authSuccessRate.add(0);
    if (authMode !== "policy") {
      authErrorRate.add(1);
    }
    return;
  }

  if (response?.status === 401) {
    auth401Count.add(1);
    if (failFastEnabled) {
      failFast401 += 1;
    }
  }
  if (failFastEnabled) {
    failFastSamples += 1;
    const inFailFastWindow = Date.now() - testStartedAt <= failFastWindowMs;
    if (inFailFastWindow && failFastSamples >= failFastMinSamples) {
      const ratio = failFast401 / failFastSamples;
      if (ratio >= failFast401Ratio) {
        fail(
          `invalid credentials: 401 ratio ${ratio.toFixed(2)} in first ${Math.round(
            failFastWindowMs / 1000
          )}s (samples=${failFastSamples})`
        );
      }
    }
  }
  if (response?.status === 400) {
    auth400Count.add(1);
  } else if (response?.status === 403) {
    auth403Count.add(1);
  } else if (response?.status === 500) {
    auth500Count.add(1);
    auth5xxCount.add(1);
  } else if (response?.status === 502) {
    auth502Count.add(1);
    auth5xxCount.add(1);
  } else if (response?.status === 503) {
    auth503Count.add(1);
    auth5xxCount.add(1);
  } else if (response?.status === 504) {
    auth504Count.add(1);
    auth5xxCount.add(1);
  } else if ((response?.status || 0) >= 500) {
    auth5xxCount.add(1);
  } else if (response?.status !== 200 && response?.status !== 401 && response?.status !== 429) {
    authOtherStatusCount.add(1);
  }

  authPolicy429Rate.add(0);
  let accessToken = response?.cookies?.access_token?.[0]?.value || null;
  if (!accessToken) {
    const setCookieHeader = response?.headers?.["Set-Cookie"] || response?.headers?.["set-cookie"] || "";
    const m = String(setCookieHeader).match(/(?:^|;\s*)access_token=([^;]+)/);
    if (m?.[1]) {
      accessToken = m[1];
    }
  }
  const ok = check(response, { "auth status is 200": (r) => r.status === 200 });
  if (ok && !accessToken) {
    authMissingCookieCount.add(1);
  }
  if (!ok || !accessToken) {
    authErrorRate.add(1);
    authSuccessRate.add(0);
    return;
  }
  authErrorRate.add(0);
  authSuccessRate.add(1);
}

export function handleSummary(data) {
  const metrics = data.metrics || {};
  return {
    "load-test-results/auth-load-summary.json": JSON.stringify(data, null, 2),
    stdout: `\n=== Auth Load Summary ===\nmode: ${authMode}\nrequests: ${metrics.http_reqs?.values?.count || 0}\n400_count: ${metrics.auth_400_count?.values?.count || 0}\n401_count: ${metrics.auth_401_count?.values?.count || 0}\n403_count: ${metrics.auth_403_count?.values?.count || 0}\n429_count: ${metrics.auth_429_count?.values?.count || 0}\n500_count: ${metrics.auth_500_count?.values?.count || 0}\n502_count: ${metrics.auth_502_count?.values?.count || 0}\n503_count: ${metrics.auth_503_count?.values?.count || 0}\n504_count: ${metrics.auth_504_count?.values?.count || 0}\n5xx_count: ${metrics.auth_5xx_count?.values?.count || 0}\nother_status_count: ${metrics.auth_other_status_count?.values?.count || 0}\nmissing_cookie_count: ${metrics.auth_missing_cookie_count?.values?.count || 0}\ntimeout_count: ${metrics.auth_timeout_count?.values?.count || 0}\neof_count: ${metrics.auth_eof_count?.values?.count || 0}\nerror_rate: ${metrics.auth_error_rate?.values?.rate || 0}\n`,
  };
}
