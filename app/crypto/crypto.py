"""
Secure Medical Data Gateway - Crypto module
"""
import asyncio
import subprocess
from pathlib import Path
import hashlib
from typing import Tuple


class CryptoManager:
    """Менеджер для работы с age"""

    def __init__(self):
        self.base_dir = Path.cwd()

    @staticmethod
    def check_age_installed() -> bool:
        """Проверка установлен ли age"""
        try:
            subprocess.run(["age", "--version"], 
                         capture_output=True, text=True, timeout=5, check=True)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return False

    @staticmethod
    async def generate_keypair(output_path: Path) -> Tuple[str, str]:
        """Генерация ключевой пары age"""
        # Создаем директорию, если нет
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        process = await asyncio.create_subprocess_exec(
            "age-keygen", "-o", str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Ошибка генерации ключей: {stderr.decode()}")
        
        if not output_path.exists():
            raise FileNotFoundError("Не удалось создать ключ")

        with open(output_path, 'r') as f:
            content = f.read()

        private_key = content.strip()
        public_key = None
        for line in content.splitlines():
            if line.startswith("# public key:"):
                public_key = line.split(": ")[1].strip()
                break

        if not public_key:
            raise Exception("Не удалось извлечь публичный ключ")

        return private_key, public_key

    @staticmethod
    def calculate_hash(file_path: Path) -> str:
        """SHA256 хеш файла"""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()



    
    async def encrypt_file(self, input_path: Path, output_path: Path, public_key: str):
        """Шифрование файла"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Используем абсолютные пути
        input_path_str = str(input_path.absolute())
        output_path_str = str(output_path.absolute())
        
        print(f"🔐 Шифрование: {input_path.name} → {output_path.name}")
        print(f"   Входной путь: {input_path_str}")
        print(f"   Выходной путь: {output_path_str}")
        
        # Проверяем что входной файл существует
        if not input_path.exists():
            raise FileNotFoundError(f"Input file does not exist: {input_path_str}")
        
        # Команда без shlex.quote - передаем пути напрямую
        cmd = [
            "age",
            "-e",
            "-r", public_key.strip(),
            "-o", output_path_str,  # Без кавычек!
            input_path_str          # Без кавычек!
        ]
        
        print(f"   Команда: {' '.join(cmd[:3])} ... {cmd[-2:]}")  # Логируем для отладки
        
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,
                shell=False
            )
            
            if process.returncode != 0:
                error_msg = f"Age encryption error: {process.stderr}"
                print(f"❌ {error_msg}")
                raise Exception(error_msg)
            
            if not output_path.exists():
                raise Exception(f"Output file was not created: {output_path_str}")
            
            output_size = output_path.stat().st_size
            if output_size == 0:
                raise Exception("Output file is empty")
                
            print(f"   ✅ Успешно! Размер: {output_size} байт")
            
        except subprocess.TimeoutExpired:
            raise Exception("Encryption timed out after 30 seconds")
        except Exception as e:
            print(f"❌ Исключение при шифровании: {type(e).__name__}: {e}")
            raise

    async def decrypt_file(self, encrypted_path: Path, output_path: Path, private_key_path: Path):
        """Дешифрование файла"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Используем абсолютные пути
        encrypted_path_str = str(encrypted_path.absolute())
        output_path_str = str(output_path.absolute())
        private_key_path_str = str(private_key_path.absolute())
        
        print(f"🔓 Дешифрование: {encrypted_path.name} → {output_path.name}")
        print(f"   Зашифрованный путь: {encrypted_path_str}")
        print(f"   Выходной путь: {output_path_str}")
        
        # Проверяем что зашифрованный файл существует
        if not encrypted_path.exists():
            raise FileNotFoundError(f"Encrypted file does not exist: {encrypted_path_str}")
        
        # Команда без shlex.quote
        cmd = [
            "age",
            "--decrypt",
            "-i", private_key_path_str,  # Без кавычек!
            "-o", output_path_str,       # Без кавычек!
            encrypted_path_str           # Без кавычек!
        ]
        
        print(f"   Команда: {' '.join(cmd[:4])} ... {cmd[-2:]}")  # Логируем для отладки
        
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,
                shell=False
            )
            
            if process.returncode != 0:
                error_msg = f"Age decryption error: {process.stderr}"
                print(f"❌ {error_msg}")
                raise Exception(error_msg)
            
            if not output_path.exists():
                raise Exception(f"Output file was not created: {output_path_str}")
            
            output_size = output_path.stat().st_size
            if output_size == 0:
                raise Exception("Output file is empty")
                
            print(f"   ✅ Успешно! Размер: {output_size} байт")
            
        except subprocess.TimeoutExpired:
            raise Exception("Decryption timed out after 30 seconds")
        except Exception as e:
            print(f"❌ Исключение при дешифровании: {type(e).__name__}: {e}")
            raise    
    

# Экземпляр модуля
crypto_manager = CryptoManager()