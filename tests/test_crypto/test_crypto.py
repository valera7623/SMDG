# tests/test_crypto/test_crypto.py
"""
Тесты для app/crypto/crypto.py
Целевое покрытие: 90-95%
"""
import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from app.crypto.crypto import CryptoManager


# ===========================================================================
# Фикстуры
# ===========================================================================

@pytest.fixture
def crypto():
    """Экземпляр CryptoManager без патчей."""
    return CryptoManager()


@pytest.fixture
def tmp_dir():
    """Временная директория, удаляется после теста."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_file(tmp_dir):
    """Тестовый текстовый файл."""
    p = tmp_dir / "sample.txt"
    p.write_text("Hello, medical world! 🏥")
    return p


@pytest.fixture
def fake_private_key(tmp_dir):
    """Фиктивный приватный ключ."""
    k = tmp_dir / "age.key"
    k.write_text("AGE-SECRET-KEY-FAKE")
    return k


# ===========================================================================
# check_age_installed
# ===========================================================================

class TestCheckAgeInstalled:
    def test_returns_true_when_age_present(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert CryptoManager.check_age_installed() is True

    def test_returns_false_when_age_missing(self):
        import subprocess
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert CryptoManager.check_age_installed() is False

    def test_returns_false_on_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("age", 5)):
            assert CryptoManager.check_age_installed() is False

    def test_returns_false_on_called_process_error(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "age")):
            assert CryptoManager.check_age_installed() is False


# ===========================================================================
# generate_keypair
# ===========================================================================

class TestGenerateKeypair:
    async def _make_process(self, returncode: int, stderr: str) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(b"", stderr.encode()))
        return proc

    async def test_success_public_key_prefix(self, tmp_dir):
        key_path = tmp_dir / "subdir" / "age.key"
        stderr = "Public key: age1abc123def456\nsome other line"
        proc = await self._make_process(0, stderr)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            pub, path = await CryptoManager.generate_keypair(key_path)

        assert pub == "age1abc123def456"
        assert path == str(key_path.absolute())

    async def test_success_hash_public_key_prefix(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        stderr = "# public key: age1xyz789\n# created: 2024"
        proc = await self._make_process(0, stderr)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            pub, path = await CryptoManager.generate_keypair(key_path)

        assert pub == "age1xyz789"

    async def test_success_generic_public_key_line(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        stderr = "Generated public key: age1generic123"
        proc = await self._make_process(0, stderr)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            pub, path = await CryptoManager.generate_keypair(key_path)

        assert pub == "age1generic123"

    async def test_raises_on_nonzero_returncode(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        proc = await self._make_process(1, "some error")

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Ошибка генерации ключей age"):
            await CryptoManager.generate_keypair(key_path)

    async def test_raises_when_public_key_not_found(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        proc = await self._make_process(0, "no key info here at all")

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Не удалось извлечь публичный ключ"):
            await CryptoManager.generate_keypair(key_path)

    async def test_creates_parent_directories(self, tmp_dir):
        key_path = tmp_dir / "deep" / "nested" / "age.key"
        stderr = "Public key: age1test"
        proc = await self._make_process(0, stderr)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await CryptoManager.generate_keypair(key_path)

        assert key_path.parent.exists()


# ===========================================================================
# encrypt
# ===========================================================================

class TestEncrypt:
    async def _make_process(self, returncode: int) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    async def test_success(self, crypto, sample_file, tmp_dir):
        out = tmp_dir / "out.age"
        out.write_bytes(b"encrypted_data")

        proc = await self._make_process(0)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch("app.crypto.crypto.calculate_hash_async", return_value="abc123") as mock_hash:
            result = await crypto.encrypt(sample_file, "age1pubkey", out)

        assert result == "abc123"
        mock_hash.assert_awaited_once_with(out)

    async def test_raises_when_input_not_found(self, crypto, tmp_dir):
        missing = tmp_dir / "missing.txt"
        out = tmp_dir / "out.age"

        with pytest.raises(FileNotFoundError, match="Входной файл не найден"):
            await crypto.encrypt(missing, "age1pubkey", out)

    async def test_raises_on_nonzero_returncode(self, crypto, sample_file, tmp_dir):
        out = tmp_dir / "out.age"
        proc = await self._make_process(1)
        proc.communicate = AsyncMock(return_value=(b"", b"age error details"))

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Ошибка шифрования age"):
            await crypto.encrypt(sample_file, "age1pubkey", out)

    async def test_raises_when_output_missing_after_encrypt(self, crypto, sample_file, tmp_dir):
        out = tmp_dir / "nonexistent_output.age"
        proc = await self._make_process(0)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Зашифрованный файл не создан или пуст"):
            await crypto.encrypt(sample_file, "age1pubkey", out)

    async def test_raises_when_output_empty(self, crypto, sample_file, tmp_dir):
        out = tmp_dir / "empty.age"
        out.write_bytes(b"")  # пустой файл
        proc = await self._make_process(0)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Зашифрованный файл не создан или пуст"):
            await crypto.encrypt(sample_file, "age1pubkey", out)

    async def test_creates_output_parent_directory(self, crypto, sample_file, tmp_dir):
        out = tmp_dir / "subdir" / "out.age"
        out_with_data = out
        proc = await self._make_process(0)

        # создаём файл после запуска процесса — имитируем age
        async def fake_communicate():
            out_with_data.parent.mkdir(parents=True, exist_ok=True)
            out_with_data.write_bytes(b"data")
            return b"", b""

        proc.communicate = fake_communicate

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch("app.crypto.crypto.calculate_hash_async", return_value="hash"):
            await crypto.encrypt(sample_file, "age1pubkey", out_with_data)

        assert out_with_data.parent.exists()


# ===========================================================================
# decrypt
# ===========================================================================

class TestDecrypt:
    async def _make_process(self, returncode: int) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    async def test_success(self, crypto, tmp_dir):
        enc = tmp_dir / "enc.age"
        enc.write_bytes(b"encrypted")
        key = tmp_dir / "age.key"
        key.write_text("FAKE-KEY")
        out = tmp_dir / "plain.txt"
        out.write_text("decrypted content")

        proc = await self._make_process(0)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             patch("app.crypto.crypto.calculate_hash_async", return_value="decr_hash") as mock_hash:
            result = await crypto.decrypt(enc, key, out)

        assert result == "decr_hash"
        mock_hash.assert_awaited_once_with(out)

    async def test_raises_when_encrypted_not_found(self, crypto, tmp_dir):
        missing = tmp_dir / "missing.age"
        key = tmp_dir / "age.key"
        out = tmp_dir / "plain.txt"

        with pytest.raises(FileNotFoundError, match="Зашифрованный файл не найден"):
            await crypto.decrypt(missing, key, out)

    async def test_raises_on_nonzero_returncode(self, crypto, tmp_dir):
        enc = tmp_dir / "enc.age"
        enc.write_bytes(b"data")
        key = tmp_dir / "age.key"
        out = tmp_dir / "plain.txt"

        proc = await self._make_process(1)
        proc.communicate = AsyncMock(return_value=(b"", b"decryption error"))

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Ошибка расшифровки age"):
            await crypto.decrypt(enc, key, out)

    async def test_raises_when_output_missing_after_decrypt(self, crypto, tmp_dir):
        enc = tmp_dir / "enc.age"
        enc.write_bytes(b"data")
        key = tmp_dir / "age.key"
        out = tmp_dir / "plain.txt"  # не создаём

        proc = await self._make_process(0)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Расшифрованный файл не создан или пуст"):
            await crypto.decrypt(enc, key, out)

    async def test_raises_when_output_empty(self, crypto, tmp_dir):
        enc = tmp_dir / "enc.age"
        enc.write_bytes(b"data")
        key = tmp_dir / "age.key"
        out = tmp_dir / "plain.txt"
        out.write_bytes(b"")

        proc = await self._make_process(0)

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(Exception, match="Расшифрованный файл не создан или пуст"):
            await crypto.decrypt(enc, key, out)


# ===========================================================================
# generate_new_keypair
# ===========================================================================

class TestGenerateNewKeypair:
    async def _make_process(self, returncode: int, stdout: str, stderr: str) -> AsyncMock:
        proc = AsyncMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(stdout.encode(), stderr.encode()))
        return proc

    async def test_success_age1_in_stdout(self, tmp_dir):
        key_path = tmp_dir / "new_age.key"
        proc = await self._make_process(0, "age1newpublickey123abc\n", "")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            path, pub = await CryptoManager.generate_new_keypair(key_path)

        assert pub == "age1newpublickey123abc"
        assert path == key_path

    async def test_success_hash_public_key_in_stderr(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        proc = await self._make_process(0, "", "# public key: age1fromstderr456\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            _, pub = await CryptoManager.generate_new_keypair(key_path)

        assert pub == "age1fromstderr456"

    async def test_success_generic_public_key_line(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        proc = await self._make_process(0, "", "output public key: age1generic789\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            _, pub = await CryptoManager.generate_new_keypair(key_path)

        assert pub == "age1generic789"

    async def test_raises_on_nonzero_returncode(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        proc = await self._make_process(1, "", "keygen failed")

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(RuntimeError, match="age-keygen failed"):
            await CryptoManager.generate_new_keypair(key_path)

    async def test_raises_when_key_not_extractable(self, tmp_dir):
        key_path = tmp_dir / "age.key"
        proc = await self._make_process(0, "no key info", "also nothing")

        with patch("asyncio.create_subprocess_exec", return_value=proc), \
             pytest.raises(RuntimeError, match="Не удалось извлечь публичный ключ"):
            await CryptoManager.generate_new_keypair(key_path)

    async def test_creates_parent_directories(self, tmp_dir):
        key_path = tmp_dir / "deep" / "path" / "age.key"
        proc = await self._make_process(0, "age1createdirs\n", "")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await CryptoManager.generate_new_keypair(key_path)

        assert key_path.parent.exists()


# ===========================================================================
# reencrypt_file
# ===========================================================================

class TestReencryptFile:
    async def test_skips_missing_file(self, crypto, tmp_dir):
        missing = tmp_dir / "missing.age"
        with patch.object(crypto, "decrypt") as mock_decrypt:
            await crypto.reencrypt_file(missing, tmp_dir / "key", "age1pub")
            mock_decrypt.assert_not_called()

    async def test_skips_directory(self, crypto, tmp_dir):
        subdir = tmp_dir / "adir"
        subdir.mkdir()
        with patch.object(crypto, "decrypt") as mock_decrypt:
            await crypto.reencrypt_file(subdir, tmp_dir / "key", "age1pub")
            mock_decrypt.assert_not_called()

    async def test_success_flow(self, crypto, tmp_dir):
        enc_file = tmp_dir / "data.age"
        enc_file.write_bytes(b"original encrypted data")
        old_key = tmp_dir / "old.key"
        old_key.write_text("OLD-KEY")
        new_pub = "age1newpubkey"

        async def fake_decrypt(enc_path, key_path, out_path):
            out_path.write_text("decrypted plaintext")

        new_enc_content = b"new encrypted content"

        async def fake_create_subprocess(*args, **kwargs):
            # записываем tmp файл (второй аргумент --output)
            out_arg_idx = list(args).index("--output") + 1
            out_path = Path(args[out_arg_idx])
            out_path.write_bytes(new_enc_content)
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        mock_audit = MagicMock()

        with patch.object(crypto, "decrypt", side_effect=fake_decrypt), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess), \
             patch("app.crypto.crypto.audit_logger", mock_audit):
            await crypto.reencrypt_file(enc_file, old_key, new_pub)

        # После атомарной замены файл должен содержать новое содержимое
        assert enc_file.read_bytes() == new_enc_content
        mock_audit.log_operation.assert_called_once()

    async def test_raises_when_encryption_fails(self, crypto, tmp_dir):
        enc_file = tmp_dir / "data.age"
        enc_file.write_bytes(b"data")

        async def fake_decrypt(enc_path, key_path, out_path):
            out_path.write_text("plain")

        async def fake_create_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"encrypt error"))
            return proc

        with patch.object(crypto, "decrypt", side_effect=fake_decrypt), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess), \
             pytest.raises(RuntimeError, match="Перешифровка"):
            await crypto.reencrypt_file(enc_file, tmp_dir / "key", "age1pub")

    async def test_raises_when_new_file_empty(self, crypto, tmp_dir):
        enc_file = tmp_dir / "data.age"
        enc_file.write_bytes(b"data")

        async def fake_decrypt(enc_path, key_path, out_path):
            out_path.write_text("plain")

        async def fake_create_subprocess(*args, **kwargs):
            out_arg_idx = list(args).index("--output") + 1
            out_path = Path(args[out_arg_idx])
            out_path.write_bytes(b"")  # пустой — должен упасть
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch.object(crypto, "decrypt", side_effect=fake_decrypt), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess), \
             pytest.raises(RuntimeError, match="Новый зашифрованный файл пуст"):
            await crypto.reencrypt_file(enc_file, tmp_dir / "key", "age1pub")


# ===========================================================================
# rotate_keys
# ===========================================================================

class TestRotateKeys:
    async def test_raises_when_encrypted_dir_missing(self, crypto, tmp_dir):
        with patch("app.crypto.crypto.ENCRYPTED_DIR", tmp_dir / "nonexistent"), \
             pytest.raises(RuntimeError, match="Директория encrypted не найдена"):
            await crypto.rotate_keys()

    async def test_raises_when_private_key_missing(self, crypto, tmp_dir):
        enc_dir = tmp_dir / "encrypted"
        enc_dir.mkdir()

        with patch("app.crypto.crypto.ENCRYPTED_DIR", enc_dir), \
             patch("app.crypto.crypto.PRIVATE_KEY_PATH", tmp_dir / "missing.key"), \
             pytest.raises(RuntimeError, match="Старый приватный ключ не найден"):
            await crypto.rotate_keys()

    async def test_success_no_files(self, crypto, tmp_dir):
        enc_dir = tmp_dir / "encrypted"
        enc_dir.mkdir()
        old_key = tmp_dir / "age.key"
        old_key.write_text("OLD-KEY")
        backup_dir = str(tmp_dir / "backups")

        async def fake_generate_new_keypair(path):
            path.write_text("NEW-KEY")
            return path, "age1rotatedpubkey123"

        mock_audit = MagicMock()

        with patch("app.crypto.crypto.ENCRYPTED_DIR", enc_dir), \
             patch("app.crypto.crypto.PRIVATE_KEY_PATH", old_key), \
             patch.object(crypto, "generate_new_keypair", side_effect=fake_generate_new_keypair), \
             patch("app.crypto.crypto.audit_logger", mock_audit):
            result = await crypto.rotate_keys(backup_old_key=True, backup_dir=backup_dir)

        assert result == "age1rotatedpubkey123"
        # публичный ключ записан
        pub_path = old_key.with_name("age.pub")
        assert pub_path.read_text().strip() == "age1rotatedpubkey123"
        # бэкап создан
        backups = list(Path(backup_dir).glob("age.key.bak.*"))
        assert len(backups) == 1
        assert mock_audit.log_operation.call_count >= 2

    async def test_success_with_files(self, crypto, tmp_dir):
        enc_dir = tmp_dir / "encrypted"
        enc_dir.mkdir()
        # создаём .age файлы
        (enc_dir / "file1.age").write_bytes(b"enc1")
        (enc_dir / "file2.age").write_bytes(b"enc2")
        # не .age — должен игнорироваться
        (enc_dir / "readme.txt").write_text("ignore me")

        old_key = tmp_dir / "age.key"
        old_key.write_text("OLD-KEY")

        async def fake_generate_new_keypair(path):
            path.write_text("NEW-KEY")
            return path, "age1newrotated456"

        reencrypt_calls = []

        async def fake_reencrypt(file_path, old_private, new_pub):
            reencrypt_calls.append(file_path.name)

        mock_audit = MagicMock()

        with patch("app.crypto.crypto.ENCRYPTED_DIR", enc_dir), \
             patch("app.crypto.crypto.PRIVATE_KEY_PATH", old_key), \
             patch.object(crypto, "generate_new_keypair", side_effect=fake_generate_new_keypair), \
             patch.object(crypto, "reencrypt_file", side_effect=fake_reencrypt), \
             patch("app.crypto.crypto.audit_logger", mock_audit):
            result = await crypto.rotate_keys(backup_old_key=False)

        assert result == "age1newrotated456"
        assert set(reencrypt_calls) == {"file1.age", "file2.age"}

    async def test_no_backup_when_disabled(self, crypto, tmp_dir):
        enc_dir = tmp_dir / "encrypted"
        enc_dir.mkdir()
        old_key = tmp_dir / "age.key"
        old_key.write_text("OLD-KEY")
        backup_dir = tmp_dir / "backups"

        async def fake_generate_new_keypair(path):
            path.write_text("NEW-KEY")
            return path, "age1nobackup789"

        with patch("app.crypto.crypto.ENCRYPTED_DIR", enc_dir), \
             patch("app.crypto.crypto.PRIVATE_KEY_PATH", old_key), \
             patch.object(crypto, "generate_new_keypair", side_effect=fake_generate_new_keypair), \
             patch("app.crypto.crypto.audit_logger", MagicMock()):
            await crypto.rotate_keys(backup_old_key=False, backup_dir=str(backup_dir))

        # бэкапов не должно быть
        if backup_dir.exists():
            assert list(backup_dir.glob("age.key.bak.*")) == []

    async def test_propagates_exception_from_generate(self, crypto, tmp_dir):
        enc_dir = tmp_dir / "encrypted"
        enc_dir.mkdir()
        old_key = tmp_dir / "age.key"
        old_key.write_text("OLD-KEY")

        async def failing_generate(path):
            raise RuntimeError("keygen exploded")

        mock_audit = MagicMock()

        with patch("app.crypto.crypto.ENCRYPTED_DIR", enc_dir), \
             patch("app.crypto.crypto.PRIVATE_KEY_PATH", old_key), \
             patch.object(crypto, "generate_new_keypair", side_effect=failing_generate), \
             patch("app.crypto.crypto.audit_logger", mock_audit), \
             pytest.raises(RuntimeError, match="keygen exploded"):
            await crypto.rotate_keys()

        # Должна быть запись об ошибке
        calls = [c[0][0] for c in mock_audit.log_operation.call_args_list]
        assert "key_rotation_failed" in calls


# ===========================================================================
# encrypt_file / decrypt_file  (backward-compat wrappers)
# ===========================================================================

class TestCompatibilityWrappers:
    async def test_encrypt_file_delegates_to_encrypt(self, crypto, sample_file, tmp_dir):
        out = tmp_dir / "out.age"
        with patch.object(crypto, "encrypt", new=AsyncMock(return_value="hashXYZ")) as mock_enc:
            result = await crypto.encrypt_file(sample_file, "age1pub", out)
        mock_enc.assert_awaited_once_with(sample_file, "age1pub", out)
        assert result == "hashXYZ"

    async def test_decrypt_file_delegates_to_decrypt(self, crypto, tmp_dir):
        enc = tmp_dir / "enc.age"
        key = tmp_dir / "age.key"
        out = tmp_dir / "plain.txt"
        with patch.object(crypto, "decrypt", new=AsyncMock(return_value="hashABC")) as mock_dec:
            await crypto.decrypt_file(enc, key, out)
        mock_dec.assert_awaited_once_with(enc, key, out)



        
        
