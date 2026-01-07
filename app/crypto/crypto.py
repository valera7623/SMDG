"""
Secure Medical Data Gateway - Crypto module
"""
import asyncio
import shlex
import subprocess
from pathlib import Path
import hashlib
from typing import Tuple


class CryptoManager:
    """Менеджер для асинхронной работы с age"""

    def __init__(self):
        self.base_dir = Path.cwd()

    @staticmethod
    def check_age_installed() -> bool:
        """Проверка, установлен ли age в системе"""
        try:
            subprocess.run(["age", "--version"],
                           capture_output=True, text=True, timeout=5, check=True)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return False

    @staticmethod
    async def generate_keypair(output_path: Path) -> Tuple[str, str]:
        """Генерация ключевой пары age (асинхронно)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "age-keygen",
            "-o", shlex.quote(str(output_path.absolute()))
        ]
        
        print(f"🔑 Генерация ключей: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace').strip()
            raise Exception(f"Ошибка генерации ключей age: {error_msg}")
        
        if not output_path.exists():
            raise FileNotFoundError(f"Файл ключа не создан: {output_path}")
        
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        public_key = None
        for line in content.splitlines():
            if line.startswith("# public key:"):
                public_key = line.split(": ", 1)[1].strip()
                break
        
        if not public_key:
            raise Exception("Не удалось извлечь публичный ключ из вывода age-keygen")
        
        private_key = content.splitlines()[0] if content.splitlines() else ""
        return private_key, public_key

    @staticmethod
    def calculate_hash(file_path: Path) -> str:
        """SHA256 хеш файла (синхронно — быстро и безопасно)"""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    async def encrypt_file(input_path: Path, output_path: Path, public_key: str) -> None:
        """Шифрование файла с помощью age и публичного ключа (асинхронно)"""
        if not input_path.exists():
            raise FileNotFoundError(f"Исходный файл не найден: {input_path}")
        
        input_str = shlex.quote(str(input_path.absolute()))
        output_str = shlex.quote(str(output_path.absolute()))
        
        cmd = [
            "age",
            "--encrypt",
            "--recipient", public_key,
            "--output", output_str,
            input_str
        ]
        
        print(f"🔒 Шифрование: {' '.join(cmd[:6])} ... {cmd[-1]}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace').strip()
            raise Exception(f"Ошибка шифрования age: {error_msg}")
        
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception(f"Зашифрованный файл не создан или пуст: {output_path}")
        
        print(f"   ✅ Файл успешно зашифрован → {output_path.name}")

    @staticmethod
    async def decrypt_file(encrypted_path: Path, output_path: Path, private_key_path: Path) -> None:
        """Расшифровка файла с помощью приватного ключа (асинхронно)"""
        if not encrypted_path.exists():
            raise FileNotFoundError(f"Зашифрованный файл не найден: {encrypted_path}")
        
        if not private_key_path.exists():
            raise FileNotFoundError(f"Приватный ключ не найден: {private_key_path}")
        
        encrypted_str = shlex.quote(str(encrypted_path.absolute()))
        output_str = shlex.quote(str(output_path.absolute()))
        private_key_str = shlex.quote(str(private_key_path.absolute()))
        
        cmd = [
            "age",
            "--decrypt",
            "--identity", private_key_str,
            "--output", output_str,
            encrypted_str
        ]
        
        print(f"🔓 Расшифровка: {' '.join(cmd[:6])} ... {cmd[-1]}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace').strip()
            raise Exception(f"Ошибка расшифровки age: {error_msg}")
        
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception(f"Расшифрованный файл не создан или пуст: {output_path}")
        
        print(f"   ✅ Файл успешно расшифрован → {output_path.name}")


# Глобальный экземпляр менеджера
crypto_manager = CryptoManager()