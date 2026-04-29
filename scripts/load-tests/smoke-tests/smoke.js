import http from "k6/http";
import { check } from "k6";
import { config } from "../config/config.js";

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    http_req_failed: ["rate<0.05"],
    checks: ["rate>0.95"],
  },
};

export default function () {
  const health = http.get(`${config.baseUrl}/health`);
  check(health, { "health status is 200": (r) => r.status === 200 });
  const ready = http.get(`${config.baseUrl}/health/ready`);
  check(ready, { "ready status is 200": (r) => r.status === 200 });

  const adminUser = __ENV.ADMIN_USER || config.adminUser || "admin";
  const passwordCandidates = [
    __ENV.ADMIN_PASSWORD,
    config.adminPassword,
    "admin123",
    "admin",
  ].filter((v, i, arr) => !!v && arr.indexOf(v) === i);

  let loginResp = null;
  let token = null;
  const requireAuth = (__ENV.SMOKE_REQUIRE_AUTH || "false").toLowerCase() === "true";
  const loginExpectedStatuses = requireAuth
    ? http.expectedStatuses(200)
    : http.expectedStatuses(200, 401);

  for (const password of passwordCandidates) {
    const resp = http.post(
      `${config.baseUrl}/api/auth/login`,
      `username=${encodeURIComponent(adminUser)}&password=${encodeURIComponent(password)}`,
      {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        responseCallback: loginExpectedStatuses,
      },
    );
    const respToken = resp.cookies?.access_token?.[0]?.value || null;
    if (resp.status === 200 && respToken) {
      loginResp = resp;
      token = respToken;
      break;
    }
  }

  check({ token }, {
    "auth token available (or auth optional)": (v) => !!v.token || !requireAuth,
  });

  if (!token) {
    console.warn("Smoke auth skipped: no valid credentials found. Set ADMIN_PASSWORD or SMOKE_REQUIRE_AUTH=true.");
    return;
  }

  check(loginResp, {
    "login status is 200": (r) => r.status === 200,
    "login has access_token cookie": (r) => !!r.cookies?.access_token?.[0]?.value,
  });

  const listResp = http.get(`${config.baseUrl}/api/list`, {
    headers: token ? { Cookie: `access_token=${token}` } : {},
  });
  check(listResp, { "list status is 200": (r) => r.status === 200 });
}
