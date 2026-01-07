SMDG                                                              
├─ app                                                            
│  ├─ api                                                         
│  │  ├─ __init__.py                                              
│  │  ├─ cleanup.py                                               
│  │  ├─ delete.py                                                
│  │  ├─ download.py                                              
│  │  ├─ list.py                                                  
│  │  ├─ stats.py                                                 
│  │  └─ upload.py                                                
│  ├─ audit                                                       
│  │  └─ audit.py                                                 
│  ├─ config                                                      
│  │  └─ settings.py                                              
│  ├─ core                                                        
│  │  ├─ __init__.py                                              
│  │  ├─ audit.py                                                 
│  │  ├─ auth.py                                                  
│  │  ├─ cleanup.py                                               
│  │  └─ storage.py                                               
│  ├─ crypto                                                      
│  │  └─ crypto.py                                                
│  ├─ keys                                                        
│  │  ├─ age.key                                                  
│  │  └─ age.pub                                                  
│  ├─ templates                                                   
│  │  ├─ error.html                                               
│  │  ├─ result.html                                              
│  │  └─ upload.html                                              
│  ├─ core.py                                                     
│  └─ main.py                                                     
├─ decrypted                                                      
├─ encrypted                                                      
├─ keys                                                           
│  ├─ age.key                                                     
│  └─ age.pub                                                     
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
├─ uploads                                                        
├─ venv                                                                                                             
├─ Dockerfile                                                     
├─ MVP.md                                                         
├─ README.md                                                      
├─ clean_project.py                                               
├─ docker-compose.yml                                             
├─ private_key.key                                                
├─ public_key.key                                                 
├─ requirements.txt                                               
├─ test_delete.py                                                 
├─ test_file.txt                                                  
├─ test_stats.py                                                  
└─ медицинский_протокол.txt                                       

### Безопасность ключей

- Никогда не запускайте сервис в production с `DEV_MODE=true`
- Приватный ключ `keys/age.key` должен быть создан один раз и сохранён в безопасном месте
- Используйте Docker volumes для сохранения ключей между перезапусками:
  ```yaml
  volumes:
    - ./keys:/app/keys:ro  # или через docker secrets в swarm/kubernetes


chmod +x generate-self-signed.sh
./generate-self-signed.sh
docker-compose up --build  - запуск с самоподписанным сертификатом