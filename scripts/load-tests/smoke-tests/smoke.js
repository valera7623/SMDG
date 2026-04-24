import http from "k6/http";
import { check } from "k6";
import { config } from "../config/config.js";

export const options = {
  vus: 1,
  duration: "10s",
  thresholds: {
    http_req_failed: ["rate==0"],
    checks: ["rate==1"],
  },
};

export default function () {
  const health = http.get(`${config.baseUrl}/health`);
  check(health, { "health status is 200": (r) => r.status === 200 });

  const loginResp = http.post(
    `${config.baseUrl}/api/auth/login`,
    `username=${encodeURIComponent(config.adminUser)}&password=${encodeURIComponent(config.adminPassword)}`,
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } },
  );
  check(loginResp, {
    "login status is 200": (r) => r.status === 200,
    "login has access_token cookie": (r) => !!r.cookies?.access_token?.[0]?.value,
  });

  const token = loginResp.cookies?.access_token?.[0]?.value;
  const listResp = http.get(`${config.baseUrl}/api/list`, {
    headers: token ? { Cookie: `access_token=${token}` } : {},
  });
  check(listResp, { "list status is 200": (r) => r.status === 200 });
}
