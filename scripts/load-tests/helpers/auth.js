import http from "k6/http";
import { check } from "k6";
import { config } from "../config/config.js";

export function login(username = config.adminUser, password = config.adminPassword) {
  const url = `${config.baseUrl}/api/auth/login`;
  const payload = `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`;
  const params = { headers: { "Content-Type": "application/x-www-form-urlencoded" } };
  const response = http.post(url, payload, params);

  check(response, {
    "login status is 200": (r) => r.status === 200,
    "login cookie exists": (r) => !!r.cookies?.access_token?.[0]?.value,
  });

  return {
    response,
    cookies: response.cookies || {},
    accessToken: response.cookies?.access_token?.[0]?.value || null,
  };
}

export function getAuthCookies(username = config.adminUser, password = config.adminPassword) {
  return login(username, password).cookies;
}

export function getCookieHeader(cookies) {
  const token = cookies?.access_token?.[0]?.value;
  return token ? { Cookie: `access_token=${token}` } : {};
}
