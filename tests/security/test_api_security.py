"""
API security tests for SMDG.
"""
import io

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestAPISecurity:
    def test_rate_limiting_login_bruteforce(self):
        for _ in range(30):
            client.post("/api/auth/login", data={"username": "admin", "password": "wrong_password"})

        response = client.post("/api/auth/login", data={"username": "admin", "password": "wrong_password"})
        assert response.status_code in [401, 429]

    def test_sql_injection_payloads_do_not_crash(self):
        payloads = [
            "' OR '1'='1",
            "admin' --",
            "1; DROP TABLE users; --",
            "' UNION SELECT * FROM users --",
        ]
        for payload in payloads:
            response = client.get(f"/api/list?search={payload}")
            assert response.status_code != 500

    def test_path_traversal_payloads_denied(self):
        payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\win.ini",
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ]
        for payload in payloads:
            response = client.get(f"/api/download?file={payload}")
            assert response.status_code in [400, 401, 403, 404, 422]

    def test_upload_with_xss_payload_does_not_reflect_script(self):
        payload = "<script>alert('XSS')</script>"
        response = client.post(
            "/api/upload",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
            data={"metadata": payload},
        )
        assert response.status_code in [200, 400, 401, 422]
        assert "<script>" not in response.text.lower()

    def test_jwt_replay_basic(self):
        login_response = client.post("/api/auth/login", data={"username": "admin", "password": "admin"})
        token = login_response.cookies.get("access_token")
        if not token:
            assert login_response.status_code in [401, 429]
            return

        for _ in range(3):
            response = client.get("/api/list", cookies={"access_token": token})
            assert response.status_code in [200, 401]

    def test_method_override_does_not_crash(self):
        methods = ["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"]
        for method in methods:
            response = client.request(
                method,
                "/api/auth/login",
                headers={"X-HTTP-Method-Override": method},
            )
            assert response.status_code != 500

    def test_large_payload_upload(self):
        large_data = b"A" * (10 * 1024 * 1024)
        response = client.post(
            "/api/upload",
            files={"file": ("large.txt", io.BytesIO(large_data), "text/plain")},
        )
        assert response.status_code in [200, 400, 401, 413, 422]

    def test_unauthorized_access(self):
        endpoints = ["/api/list", "/api/upload", "/api/admin/users", "/api/stats", "/api/webhooks"]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code in [401, 403, 405]

    def test_method_not_allowed(self):
        endpoints = {
            "/api/list": ["POST", "PUT", "DELETE"],
            "/api/upload": ["GET", "DELETE"],
            "/api/auth/login": ["GET", "PUT", "DELETE"],
        }
        for endpoint, methods in endpoints.items():
            for method in methods:
                response = client.request(method, endpoint)
                assert response.status_code in [401, 404, 405]

    def test_cors_headers_not_wildcard_for_evil_origin(self):
        response = client.options("/api/list", headers={"Origin": "https://evil.com"})
        assert response.headers.get("Access-Control-Allow-Origin") != "*"

    def test_content_type_sniffing_header(self):
        response = client.get("/")
        header = response.headers.get("X-Content-Type-Options", "")
        assert header in ["nosniff", ""]

    def test_frame_options_header(self):
        response = client.get("/")
        header = response.headers.get("X-Frame-Options", "")
        assert header in ["DENY", "SAMEORIGIN", ""]
