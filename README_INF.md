(smdg-py3.12) username@DESKTOP-M014DEI:/home/ubuntu/SMDG$ tree
.
├── Dockerfile
├── MVP.md
├── README.md
├── alembic.ini
├── app
│   ├── api
│   │   ├── __init__.py
│   │   ├── admin_users.py
│   │   ├── auth.py
│   │   ├── cleanup.py
│   │   ├── delete.py
│   │   ├── delete_user.py
│   │   ├── download.py
│   │   ├── list.py
│   │   ├── stats.py
│   │   └── upload.py
│   ├── audit
│   │   └── audit.py
│   ├── cli.py
│   ├── core
│   │   ├── __init__.py
│   │   ├── audit.py
│   │   ├── auth.py
│   │   ├── auth_utils.py
│   │   ├── cleanup.py
│   │   ├── config.py
│   │   ├── constants.py
│   │   ├── database.py
│   │   ├── middleware.py
│   │   ├── rate_limiter.py
│   │   ├── security.py
│   │   ├── storage.py
│   │   └── utils.py
│   ├── crypto
│   │   └── crypto.py
│   ├── main.py
│   ├── models
│   │   ├── file.py
│   │   ├── file_link.py
│   │   └── user.py
│   ├── schemas
│   └── templates
│       ├── error.html
│       ├── result.html
│       └── upload.html
├── audit_logs
│   └── audit.csv
├── backups
├── certs
│   ├── localhost-key.pem
│   └── localhost.pem
├── clean_project.py
├── decrypted
├── docker-compose.yml
├── encrypted
├── entrypoint.sh
├── generate_cert.sh
├── grafana
│   └── provisioning
│       ├── dashboards
│       └── datasources
│           └── prometheus.yml
├── keys
│   ├── age.key
│   └── age.pub
├── migrations
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions
│       └── 001_initial_schema.py
├── nginx-https.conf
├── poetry.lock
├── prometheus
│   └── prometheus.yml
├── pyproject.toml
├── pytest.ini
├── secrets
│   ├── admin_password.txt
│   ├── age.key
│   ├── jwt_secret.txt
│   └── postgres_password.txt
├── static
│   ├── css
│   │   ├── admin-users.css
│   │   └── style.css
│   ├── favicon.ico
│   ├── html
│   │   ├── admin.html
│   │   ├── admin_users.html
│   │   └── index.html
│   └── js
│       ├── admin-users.js
│       ├── admin.js
│       ├── core
│       │   ├── api.js
│       │   ├── config.js
│       │   └── state.js
│       ├── main.js
│       ├── modules
│       │   ├── admin-files.js
│       │   ├── admin-users.js
│       │   ├── auth.js
│       │   └── files.js
│       ├── utils
│       │   ├── dom.js
│       │   ├── formats.js
│       │   ├── modals.js
│       │   ├── notifications.js
│       │   └── validators.js
│       └── vendors
│           └── qrcode.min.js
├── test_login_limits.sh
├── tests
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api
│   │   ├── __init__.py
│   │   ├── test_api_auth.py
│   │   ├── test_auth.py
│   │   ├── test_cleanup.py
│   │   ├── test_delete.py
│   │   ├── test_download.py
│   │   ├── test_integration.py
│   │   ├── test_list.py
│   │   ├── test_stats.py
│   │   └── test_upload.py
│   ├── test_app
│   │   ├── __init__.py
│   │   └── test_main.py
│   ├── test_cli.py
│   ├── test_core
│   │   ├── __init__.py
│   │   ├── test_audit.py
│   │   ├── test_auth.py
│   │   ├── test_cleanup.py
│   │   ├── test_config.py
│   │   ├── test_database.py
│   │   ├── test_init.py
│   │   ├── test_middleware.py
│   │   ├── test_rate_limiter.py
│   │   ├── test_security.py
│   │   ├── test_storage.py
│   │   └── test_utils.py
│   ├── test_crypto
│   │   ├── __init__.py
│   │   └── test_crypto.py
│   ├── test_integration
│   │   ├── __init__.py
│   │   └── test_upload_download_flow.py
│   └── test_models
│       ├── __init__.py
│       ├── test_file.py
│       ├── test_file_link.py
│       └── test_user.py
└── uploads

39 directories, 118 files