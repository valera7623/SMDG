"""
Secure Medical Data Gateway - Crypto module
"""
import asyncio
import subprocess  # nosec B404 — только sync-probe `age --version` и вызовы через asyncio в _run_age
from pathlib import Path
import hashlib
from typing import Tuple, List
import shutil
import tempfile
from datetime import datetime

from app.core.utils import calculate_hash_async
from app.core.constants import ENCRYPTED_DIR, PRIVATE_KEY_PATH
from app.core import audit_logger


async def _run_age(cmd: list[str], err_prefix: str, err_cls: type = Exception) -> tuple[bytes, bytes]:
    """Запустить бинарник age/age-keygen и вернуть (stdout, stderr).

    Бросает исключение ``err_cls`` с префиксом ``err_prefix``, если процесс завершился с ошибкой.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr_data.decode("utf-8", errors="replace").strip()
        raise err_cls(f"{err_prefix}: {error_msg}")

    return stdout_data, stderr_data


def _parse_age_public_key(output_text: str) -> str | None:
    """Извлечь публичный ключ age из текстового вывода age-keygen.

    Поддерживает как новый формат (строка `age1...`), так и старый (`# public key: ...`
    или `Public key: ...` в разном регистре).
    """
    for raw in output_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("age1"):
            return line
        if line.startswith("Public key: ") or line.startswith("# public key: "):
            return line.split(":", 1)[1].strip()
        if "public key:" in line.lower():
            parts = line.lower().split("public key:")
            if len(parts) > 1:
                return parts[1].strip()
    return None


class CryptoManager:
    """Менеджер для асинхронной работы с age"""

    def __init__(self):
        self.base_dir = Path.cwd()

    @staticmethod
    def check_age_installed() -> bool:
        """Проверка, установлен ли age в системе"""
        age_bin = shutil.which("age")
        if not age_bin:
            return False
        try:
            subprocess.run(  # nosec B603 — argv: абсолютный путь из shutil.which + литерал --version, без пользовательского ввода
                [age_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return False

    @staticmethod
    async def generate_keypair(output_path: Path) -> Tuple[str, str]:
        """Генерация ключевой пары age (асинхронно)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["age-keygen", "-o", str(output_path.absolute())]
        print(f"🔑 Генерация ключевой пары → {output_path.name}")

        stdout_data, stderr_data = await _run_age(cmd, "Ошибка генерации ключей age")

        # Публичный ключ может быть в stderr (старые версии) или stdout (новые)
        output_text = (stdout_data + stderr_data).decode("utf-8", errors="replace")
        public_key = _parse_age_public_key(output_text)

        if not public_key:
            print("Полный вывод age-keygen для диагностики:")
            print(output_text)
            raise Exception("Не удалось извлечь публичный ключ из вывода age-keygen")

        print(f"   ✅ Ключи сгенерированы. Публичный: {public_key[:20]}...")
        return public_key, str(output_path.absolute())

    async def encrypt(self, input_path: Path, public_key: str, output_path: Path) -> str:
        """Шифрование файла с использованием публичного ключа"""
        if not input_path.exists():
            raise FileNotFoundError(f"Входной файл не найден: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "age",
            "--encrypt",
            "--recipient", public_key,
            "--output", str(output_path.absolute()),
            str(input_path.absolute())
        ]

        print(f"🔒 Шифрование: {' '.join(cmd)}")

        await _run_age(cmd, "Ошибка шифрования age")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception(f"Зашифрованный файл не создан или пуст: {output_path}")

        print(f"   ✅ Файл успешно зашифрован → {output_path.name}")

        return await calculate_hash_async(output_path)

    async def decrypt(self, encrypted_path: Path, private_key_path: Path, output_path: Path) -> str:
        """Расшифровка файла с использованием приватного ключа"""
        if not encrypted_path.exists():
            raise FileNotFoundError(f"Зашифрованный файл не найден: {encrypted_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "age",
            "--decrypt",
            "--identity", str(private_key_path.absolute()),
            "--output", str(output_path.absolute()),
            str(encrypted_path.absolute())
        ]

        print(f"🔓 Расшифровка: {' '.join(cmd)}")

        await _run_age(cmd, "Ошибка расшифровки age")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception(f"Расшифрованный файл не создан или пуст: {output_path}")

        print(f"   ✅ Файл успешно расшифрован → {output_path.name}")

        return await calculate_hash_async(output_path)

    @staticmethod
    async def generate_new_keypair(new_private_path: Path) -> Tuple[Path, str]:
        """Генерирует новую пару ключей и возвращает путь к приватному + публичный ключ как строку"""
        new_private_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["age-keygen", "-o", str(new_private_path.absolute())]
        print(f"🔑 Генерация новой пары ключей → {new_private_path.name}")

        stdout_data, stderr_data = await _run_age(cmd, "age-keygen failed", err_cls=RuntimeError)

        output_text = (stdout_data + stderr_data).decode("utf-8", errors="replace").strip()
        public_key = _parse_age_public_key(output_text)

        if not public_key:
            print("Полный вывод age-keygen для диагностики:")
            print(output_text)
            raise RuntimeError("Не удалось извлечь публичный ключ из вывода age-keygen")

        print(f"✅ Новая пара сгенерирована. Публичный: {public_key[:20]}...")
        return new_private_path, public_key



    async def reencrypt_file(self, file_path: Path, old_private_key_path: Path, new_public_key: str) -> None:
        """Перешифровывает один файл: old → plaintext → new"""
        if not file_path.exists() or not file_path.is_file():
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_plain = Path(tmpdir) / "plain"
            tmp_new_enc = Path(tmpdir) / f"{file_path.name}.new"

            # 1. Расшифровываем старым ключом
            await self.decrypt(file_path, old_private_key_path, tmp_plain)

            # 2. Шифруем новым публичным ключом
            cmd_encrypt = [
                "age",
                "--encrypt",
                "--recipient", new_public_key,
                "--output", str(tmp_new_enc.absolute()),
                str(tmp_plain.absolute())
            ]

            await _run_age(
                cmd_encrypt,
                f"Перешифровка {file_path.name} провалилась",
                err_cls=RuntimeError,
            )

            # 3. Проверяем, что новый файл не пустой
            if tmp_new_enc.stat().st_size == 0:
                raise RuntimeError(f"Новый зашифрованный файл пуст: {file_path.name}")

            # 4. Атомарная замена
            shutil.move(str(tmp_new_enc), str(file_path))

            audit_logger.log_operation(
                action="key_rotation_reencrypt",
                filename=file_path.name,
                user="system",
                reason="Ротация ключа age",
                success=True,
                metadata={"old_key": str(old_private_key_path), "new_pub": new_public_key[:10]+"..."}
            )

    async def rotate_keys(self, backup_old_key: bool = True, backup_dir: str = "/app/backups/keys") -> str:
        """Ротация ключей с бэкапом старого ключа в указанную директорию"""
        if not ENCRYPTED_DIR.exists():
            raise RuntimeError("Директория encrypted не найдена")

        old_private = PRIVATE_KEY_PATH
        if not old_private.exists():
            raise RuntimeError("Старый приватный ключ не найден")

    # Создаём директорию бэкапов
        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            new_private_tmp = Path(tmp_dir) / "new_age_private.key"
            try:
                new_private_tmp, new_pub_key_str = await self.generate_new_keypair(new_private_tmp)

                encrypted_files = [p for p in ENCRYPTED_DIR.iterdir() if p.is_file() and p.suffix == ".age"]
                total = len(encrypted_files)

                audit_logger.log_operation(
                    "key_rotation_start",
                    f"{total} files",
                    "system",
                    f"Начинаем ротацию: {total} файлов",
                    True
                )

                if total > 0:
                    for i, file_path in enumerate(encrypted_files, 1):
                        print(f"[{i}/{total}] Перешифровываю {file_path.name} ...")
                        await self.reencrypt_file(file_path, old_private, new_pub_key_str)

                # Бэкап старого ключа с timestamp
                if backup_old_key:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_file = backup_path / f"age.key.bak.{timestamp}"
                    shutil.copy(old_private, backup_file)
                    audit_logger.log_operation(
                        "key_rotation_backup",
                        str(backup_file),
                        "system",
                        f"Создан бэкап старого ключа: {backup_file.name}",
                        True,
                        metadata={"backup_path": str(backup_file)}
                    )
                    print(f"Бэкап сохранён: {backup_file}")

                # Атомарная замена
                shutil.move(str(new_private_tmp), str(old_private))
                old_private.chmod(0o600)

                pub_path = old_private.with_name("age.pub")
                pub_path.write_text(new_pub_key_str + "\n")
                pub_path.chmod(0o644)

                audit_logger.log_operation(
                    "key_rotation_success",
                    "all files",
                    "system",
                    f"Ротация завершена. Новый pub: {new_pub_key_str[:12]}...",
                    True,
                    metadata={"backup_dir": str(backup_path)}
                )

                print("Ротация завершена успешно!")
                print(f"Новый публичный ключ: {new_pub_key_str}")
                return new_pub_key_str

            except Exception as e:
                audit_logger.log_operation(
                    "key_rotation_failed",
                    "unknown",
                    "system",
                    str(e),
                    False
                )
                raise

    # Совместимость
    async def encrypt_file(self, input_path: Path, public_key: str, output_path: Path) -> str:
        """Совместимость с предыдущим кодом upload.py"""
        return await self.encrypt(input_path, public_key, output_path)

    async def decrypt_file(self, encrypted_path: Path, private_key_path: Path, output_path: Path) -> None:
        """Совместимость с предыдущим кодом download.py"""
        await self.decrypt(encrypted_path, private_key_path, output_path)


class _CryptoBackendProxy:
    """Ленивая загрузка реализации age vs ГОСТ после инициализации настроек."""

    __slots__ = ("_impl",)

    def __init__(self) -> None:
        self._impl: CryptoManager | None = None

    def _ensure(self) -> CryptoManager:
        if self._impl is None:
            from app.core.feature_flags import Feature, is_enabled

            if is_enabled(Feature.GOST_CRYPTO):
                from app.crypto.gost import GOSTCrypto

                self._impl = GOSTCrypto()
            else:
                self._impl = CryptoManager()
        return self._impl

    def __getattr__(self, name: str):
        return getattr(self._ensure(), name)


crypto_manager = _CryptoBackendProxy()


def get_crypto_backend() -> CryptoManager:
    """Текущий криптобэкенд в соответствии с DEPLOYMENT_TYPE и FEATURE_MATRIX."""
    return crypto_manager._ensure()