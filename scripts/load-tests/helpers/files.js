import http from "k6/http";
import { check } from "k6";
import { config } from "../config/config.js";

const oneMbPayload = "X".repeat(1024 * 1024);

export function buildFile(size = "1mb") {
  if (size === "1mb") {
    return {
      name: "test_1mb.bin",
      mime: "application/octet-stream",
      data: oneMbPayload,
    };
  }

  return {
    name: "test_10kb.txt",
    mime: "text/plain",
    data: "X".repeat(10 * 1024),
  };
}

export function uploadFile(cookies, fileData = buildFile("1mb"), fileName = fileData.name) {
  const url = `${config.baseUrl}/api/upload`;
  const token = cookies?.access_token?.[0]?.value;
  const params = {
    headers: {
      ...(token ? { Cookie: `access_token=${token}` } : {}),
    },
  };

  const response = http.post(
    url,
    { file: http.file(fileData.data, fileName, fileData.mime || "application/octet-stream") },
    params,
  );

  check(response, {
    "upload status is 200": (r) => r.status === 200,
  });

  return response;
}
