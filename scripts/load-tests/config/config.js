export const config = {
  baseUrl: __ENV.BASE_URL || "http://localhost:8000",
  virtualUsers: Number(__ENV.VIRTUAL_USERS || 100),
  duration: __ENV.DURATION || "5m",
  adminUser: __ENV.ADMIN_USER || "admin",
  adminPassword: __ENV.ADMIN_PASSWORD || "admin",

  thresholds: {
    http_req_failed: ["rate<0.01"],
    checks: ["rate>0.99"],
  },

  slo: {
    apiListP95Ms: Number(__ENV.SLO_API_LIST_P95_MS || 100),
    uploadP95Ms: Number(__ENV.SLO_UPLOAD_P95_MS || 5000),
    dicomP95Ms: Number(__ENV.SLO_DICOM_P95_MS || 3000),
    authP95Ms: Number(__ENV.SLO_AUTH_P95_MS || 50),
    mixedP95Ms: Number(__ENV.SLO_MIXED_P95_MS || 500),
  },

  scenarios: {
    api_load: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.API_RPS || 1000),
      timeUnit: "1s",
      duration: __ENV.API_DURATION || "5m",
      preAllocatedVUs: Number(__ENV.API_PREALLOCATED_VUS || 400),
      maxVUs: Number(__ENV.API_MAX_VUS || 2000),
    },
    upload_load: {
      executor: "constant-vus",
      vus: Number(__ENV.UPLOAD_VUS || 100),
      duration: __ENV.UPLOAD_DURATION || "5m",
    },
    dicom_load: {
      executor: "constant-vus",
      vus: Number(__ENV.DICOM_VUS || 50),
      duration: __ENV.DICOM_DURATION || "5m",
    },
    auth_load: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.AUTH_RPS || 500),
      timeUnit: "1s",
      duration: __ENV.AUTH_DURATION || "5m",
      preAllocatedVUs: Number(__ENV.AUTH_PREALLOCATED_VUS || 200),
      maxVUs: Number(__ENV.AUTH_MAX_VUS || 1500),
    },
    mixed_load: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.MIXED_RPS || 300),
      timeUnit: "1s",
      duration: __ENV.MIXED_DURATION || "10m",
      preAllocatedVUs: Number(__ENV.MIXED_PREALLOCATED_VUS || 200),
      maxVUs: Number(__ENV.MIXED_MAX_VUS || 1200),
    },
    soak_test: {
      executor: "constant-vus",
      vus: Number(__ENV.SOAK_VUS || 100),
      duration: __ENV.SOAK_DURATION || "1h",
    },
  },
};
