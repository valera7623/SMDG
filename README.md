SMDG   
├─ .github 
|   └─ workflows 
|      └─ ci.yml
├─ .vscode 
|   └─ setting.json                                                  
├─ app                                                            
│  ├─ api                                                         
│  │  ├ __init__.py
|  |  ├─ auth.py    
|  |  ├─ admin_users.py                                
│  │  ├─ cleanup.py 
|  |  ├─ delete_user.py                                          
│  │  ├─ delete.py                                                
│  │  ├─ download.py                                              
│  │  ├─ list.py                                                  
│  │  ├─ stats.py                                                 
│  │  └─ upload.py                                                
│  ├─ audit                                                       
│  │  └─ audit.py                                                 
|  |                                              
│  ├─ core                                                        
│  │  ├─ __init__.py                                              
│  │  ├─ audit.py                                                 
│  │  ├─ auth.py                                                  
│  │  ├─ cleanup.py  
|  |  ├─ config.py
|  |  ├─ constants.py
|  |  ├─ database.py
|  |  ├─ middleware.py  
|  |  ├─ rate_limiter.py
|  |  ├─ security.py
|  |  ├─ utils.py                                  
│  │  └─ storage.py                                               
│  ├─ crypto                                                      
│  │  └─ crypto.py  
|  ├─ models
|  |  ├─ file_link.py
|  |  ├─ file.py
|  |  └─ user.py 
|  ├─ schemas
|  ├─ templates
|  |  ├─ error.html
|  |  ├─ result.html
|  |  └─ upload.html
|  ├─ cli.py
|  └─ main.py
├── grafana
│   └── provisioning
│       ├── dashboards
│       └── datasources
│           └── prometheus.yml
|                                                                                               
│ 
├── audit_logs
│   ├── audit.csv
│   ├── audit_2026-03-24.log
│   ├── audit_2026-03-27.log
│   ├── audit_2026-03-28.log
│   ├── audit_2026-03-29.log
│   ├── audit_2026-03-31.log
│   ├── audit_2026-04-01.log
│   ├── audit_2026-04-02.log
│   ├── audit_2026-04-03.log
│   ├── audit_2026-04-04.log
│   └── test.log   
├── certs
│   ├── localhost-key.pem
│   └── localhost.pem
|                                                                                                        
├─ decrypted/                                                      
├─ encrypted/                                                      
├─ keys                                                           
│  ├─ age.key                                                     
│  └─ age.pub   
├── migrations
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions
│       └── 001_initial_schema.py
├── prometheus
│   └── prometheus.yml
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
|                                                                                                          
├── tests
│   ├── __init__.py
│   ├── conftest.py
│   ├── factories.py
│   ├── test_api
│   │   ├── __init__.py
│   │   ├── test_admin_user.py
│   │   ├── test_api_auth.py
│   │   ├── test_auth.py
│   │   ├── test_cleanup.py
│   │   ├── test_delete.py
│   │   ├── test_delete_user.py
│   │   ├── test_download.py
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
│   └── test_models
│       ├── __init__.py
│       ├── test_file.py
│       ├── test_file_link.py
│       └── test_user.py
|                                                                                  
├─ .dockerignore
├─ .env
├─ .env.example
├─ .env.test
├─ .gitignore
├─ alembic.ini
├─ Dockerfile  
├─ entrypoint.sh 
├─ generate_cert.sh
├─ nginx-https.conf                                                
├─ MVP.md                                                         
├─ README.md  
├─ pytest.ini                                                                                                  
├─ docker-compose.yml     
├─ setup.cfg   
├─ pyproject.toml                        
└─ poetry.lock                                
                                                  
                                      



