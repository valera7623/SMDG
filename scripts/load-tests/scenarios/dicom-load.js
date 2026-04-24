import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";
import { config } from "../config/config.js";
import { login } from "../helpers/auth.js";
import { uploadFile } from "../helpers/files.js";

const dicomLatency = new Trend("dicom_latency", true);
const dicomErrorRate = new Rate("dicom_error_rate");

const dicomBytes = open("../../test_data/CT_small.dcm", "b");

export const options = {
  scenarios: {
    dicom_load: config.scenarios.dicom_load,
  },
  thresholds: {
    dicom_latency: [`p(95)<${config.slo.dicomP95Ms}`],
    dicom_error_rate: ["rate<0.05"],
  },
};

export default function () {
  const { cookies, accessToken } = login();
  if (!accessToken) {
    dicomErrorRate.add(1);
    return;
  }

  const uploadStart = Date.now();
  const uploadResp = uploadFile(
    cookies,
    { data: dicomBytes, mime: "application/dicom", name: "CT_small.dcm" },
    `dicom_${__VU}_${__ITER}.dcm`,
  );
  dicomLatency.add(Date.now() - uploadStart);
  if (uploadResp.status !== 200) {
    dicomErrorRate.add(1);
    return;
  }

  let fileId = null;
  try {
    fileId = JSON.parse(uploadResp.body).file_id;
  } catch (e) {
    dicomErrorRate.add(1);
    return;
  }

  const viewStart = Date.now();
  const viewResp = http.post(`${config.baseUrl}/api/dicom/view-url?file_id=${fileId}`, null, {
    headers: { Cookie: `access_token=${cookies.access_token[0].value}` },
  });
  dicomLatency.add(Date.now() - viewStart);

  const viewOk = check(viewResp, { "dicom view-url status is 200": (r) => r.status === 200 });
  if (!viewOk) {
    dicomErrorRate.add(1);
    return;
  }

  const token = JSON.parse(viewResp.body).token;
  const renderStart = Date.now();
  const renderResp = http.get(`${config.baseUrl}/api/dicom/render/${fileId}?token=${token}`);
  dicomLatency.add(Date.now() - renderStart);

  const renderOk = check(renderResp, { "dicom render status is 200": (r) => r.status === 200 });
  if (!renderOk) {
    dicomErrorRate.add(1);
  }
  sleep(0.5);
}

export function handleSummary(data) {
  return {
    "load-test-results/dicom-load-summary.json": JSON.stringify(data, null, 2),
  };
}
