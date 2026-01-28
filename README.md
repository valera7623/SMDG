SMDG                                                              
├─ app                                                            
│  ├─ api                                                         
│  │  ├─ __init__.py
|  |  ├─ auth.py                                          
│  │  ├─ cleanup.py                                               
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
|  ├─ cli.py
|  └─ main.py
|
├─ keys                                                        
│  ├─ age.key                                                  
│  └─ age.pub                                                                                                
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
│  │  └─ style.css                                                
│  ├─ html                                                        
│  │  ├─ admin.html                                               
│  │  └─ index.html                                               
│  └─ js                                                          
│     ├─ admin.js                                                 
│     └─ main.js                                                                                                           
├─ tests
|   ├─ test_api
|   |   ├─ test_stats.py
|   |
|   ├─ test_app
|   ├─ test_core
|   ├─ test_crypto
|   ├─ test_integration
|   └─ test_models
|                                                  
├─ venv                                   
├─ .dockerignore
├─ .env
├─ .env.example
├─ .gitignore
├─ alembic.ini
├─ Dockerfile  
├─ entrypoint.sh  
├─ nginx-https.conf                                                
├─ MVP.md                                                         
├─ README.md                                                                                                     
├─ docker-compose.yml                                                  
└─ requirements.txt                                               
                                                  
                                      



