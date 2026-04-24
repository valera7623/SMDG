#!/usr/bin/env python3
"""
Generate deterministic test data for k6 load tests.
"""

from pathlib import Path
import json
import random


TEST_DATA_DIR = Path("test_data")


def generate_test_files() -> None:
    TEST_DATA_DIR.mkdir(exist_ok=True)

    files = [
      ("test_small_1KB.txt", 1 * 1024, b"A"),
      ("test_medium_100KB.txt", 100 * 1024, b"B"),
      ("test_large_1MB.bin", 1024 * 1024, b"C"),
      ("test_xlarge_10MB.bin", 10 * 1024 * 1024, b"D"),
    ]

    for name, size, pattern in files:
        path = TEST_DATA_DIR / name
        path.write_bytes(pattern * size)
        print(f"generated {path} ({size} bytes)")

    dicom_path = TEST_DATA_DIR / "CT_small.dcm"
    if not dicom_path.exists():
        dicom_path.write_bytes(b"DICM" + b"\0" * (1024 * 1024))
        print(f"generated placeholder {dicom_path} (1048580 bytes)")


def generate_test_users(count: int = 100) -> None:
    users = []
    random.seed(42)
    for i in range(count):
        users.append(
            {
                "username": f"testuser_{i}",
                "password": f"TestPass_{i}!",
                "email": f"user_{i}@example.com",
                "role": random.choice(["user", "doctor"]),
            }
        )

    users_path = TEST_DATA_DIR / "users.json"
    users_path.write_text(json.dumps(users, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"generated {users_path} ({count} users)")


if __name__ == "__main__":
    generate_test_files()
    generate_test_users()
    print("done")
