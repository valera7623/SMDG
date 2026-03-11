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
|                                                                                                
│ 
├─ audit_logs/   
├─ certs/                                                                                                        
├─ decrypted/                                                      
├─ encrypted/                                                      
├─ keys                                                           
│  ├─ age.key                                                     
│  └─ age.pub   
├─ migrations
├─ secrets/                                             
├─ static                                                         
│  ├─ css 
|  |  ├─ admin-users.css                                                    
│  │  └─ style.css                                                
│  ├─ html 
|  |  ├─ admin_users.html                                                   
│  │  ├─ admin.html                                               
│  │  └─ index.html                                               
│  └─ js 
|     ├─ admin-users.js                                                    
│     ├─ admin.js 
|     ├─ qrcode.min.js                                                
│     └─ main.js
|                                                                                                          
├─ tests
|   ├─ test_api
|   ├─ test_app
|   ├─ test_core
|   ├─ test_crypto
|   ├─ test_integration
|   ├─ test_models
|   ├─ conftest.py
|   └─ test_cli.py
|                                                                                  
├─ .dockerignore
├─ .env
├─ .env.example
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
                                                  
                                      



