import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from app.crypto.crypto import CryptoManager, crypto_manager


def test_crypto_manager_initialization():
    """Тест инициализации CryptoManager"""
    crypto = CryptoManager()
    assert crypto is not None
    assert hasattr(crypto, 'base_dir')
    assert isinstance(crypto.base_dir, Path)


def test_check_age_installed():
    """Тест проверки установки age"""
    with patch('subprocess.run') as mock_run:
        # Тест когда age установлен
        mock_run.return_value.returncode = 0
        result = CryptoManager.check_age_installed()
        assert result is True
        
        # Тест когда age не установлен
        mock_run.side_effect = FileNotFoundError()
        result = CryptoManager.check_age_installed()
        assert result is False


@pytest.mark.asyncio
async def test_generate_keypair(tmp_path):
    """Тест генерации ключевой пары"""
    crypto = CryptoManager()
    output_path = tmp_path / "test.key"
    
    # Мокаем subprocess
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (
            b"",  # stdout
            b"Public key: age1testpublickey123\n"  # stderr
        )
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process
        
        public_key, private_key_path = await crypto.generate_keypair(output_path)
        
        assert public_key == "age1testpublickey123"
        assert private_key_path == str(output_path.absolute())
        assert mock_subprocess.called


@pytest.mark.asyncio
async def test_encrypt_decrypt_file(tmp_path):
    """Тест шифрования и дешифрования файла"""
    crypto = CryptoManager()
    
    # Создаем тестовые файлы
    input_file = tmp_path / "test.txt"
    input_file.write_text("Test content for encryption")
    
    encrypted_file = tmp_path / "test.txt.age"
    decrypted_file = tmp_path / "decrypted.txt"
    
    public_key = "age1testpublickey123"
    
    # Мокаем subprocess для шифрования
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process
        
        # Мокаем calculate_hash
        with patch('app.crypto.crypto.calculate_hash') as mock_hash:
            mock_hash.return_value = "test_hash_123"
            
            # Шифруем
            hash_result = await crypto.encrypt(input_file, public_key, encrypted_file)
            
            assert hash_result == "test_hash_123"
            assert mock_subprocess.called
    
    # Мокаем для дешифрования
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process
        
        # Мокаем calculate_hash
        with patch('app.crypto.crypto.calculate_hash') as mock_hash:
            mock_hash.return_value = "decrypted_hash_123"
            
            # Дешифруем
            private_key_path = tmp_path / "private.key"
            hash_result = await crypto.decrypt(encrypted_file, private_key_path, decrypted_file)
            
            assert hash_result == "decrypted_hash_123"
            assert mock_subprocess.called


@pytest.mark.asyncio
async def test_encrypt_file_nonexistent(tmp_path):
    """Тест шифрования несуществующего файла"""
    crypto = CryptoManager()
    
    input_file = tmp_path / "nonexistent.txt"
    output_file = tmp_path / "output.age"
    public_key = "age1testpublickey123"
    
    with pytest.raises(FileNotFoundError):
        await crypto.encrypt(input_file, public_key, output_file)


@pytest.mark.asyncio
async def test_decrypt_file_nonexistent(tmp_path):
    """Тест дешифрования несуществующего файла"""
    crypto = CryptoManager()
    
    input_file = tmp_path / "nonexistent.age"
    output_file = tmp_path / "output.txt"
    private_key = tmp_path / "private.key"
    
    with pytest.raises(FileNotFoundError):
        await crypto.decrypt(input_file, private_key, output_file)


@pytest.mark.asyncio
async def test_generate_new_keypair(tmp_path):
    """Тест генерации новой пары ключей"""
    crypto = CryptoManager()
    output_path = tmp_path / "new.key"
    
    with patch('asyncio.create_subprocess_exec') as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (
            b"# public key: age1newpublickey456\n",
            b""
        )
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process
        
        private_path, public_key = await crypto.generate_new_keypair(output_path)
        
        assert private_path == output_path
        assert public_key == "age1newpublickey456"


def test_encrypt_file_compatibility(tmp_path):
    """Тест совместимости с предыдущим кодом"""
    crypto = CryptoManager()
    
    # Проверяем что encrypt_file вызывает encrypt
    with patch.object(crypto, 'encrypt') as mock_encrypt:
        mock_encrypt.return_value = "test_hash"
        
        result = asyncio.run(crypto.encrypt_file(
            tmp_path / "input.txt",
            "age1key",
            tmp_path / "output.age"
        ))
        
        assert result == "test_hash"
        assert mock_encrypt.called


@pytest.mark.asyncio
async def test_decrypt_file_compatibility(tmp_path):
    """Тест совместимости метода decrypt_file"""
    crypto = CryptoManager()
    
    # Проверяем что decrypt_file вызывает decrypt
    with patch.object(crypto, 'decrypt') as mock_decrypt:
        mock_decrypt.return_value = "test_hash"
        
        await crypto.decrypt_file(
            tmp_path / "input.age",
            tmp_path / "private.key",
            tmp_path / "output.txt"
        )
        
        assert mock_decrypt.called


def test_crypto_manager_global_instance():
    """Тест глобального экземпляра crypto_manager"""
    assert crypto_manager is not None
    assert isinstance(crypto_manager, CryptoManager)
    assert crypto_manager.base_dir == Path.cwd()


@pytest.mark.asyncio
async def test_rotate_keys_error_no_encrypted_dir(tmp_path):
    """Тест ротации ключей когда нет encrypted директории"""
    crypto = CryptoManager()
    
    with patch('app.crypto.crypto.ENCRYPTED_DIR', tmp_path / "nonexistent"):
        with pytest.raises(RuntimeError, match="Директория encrypted не найдена"):
            await crypto.rotate_keys()


@pytest.mark.asyncio
async def test_rotate_keys_error_no_private_key(tmp_path):
    """Тест ротации ключей когда нет приватного ключа"""
    crypto = CryptoManager()
    
    # Создаем encrypted директорию
    encrypted_dir = tmp_path / "encrypted"
    encrypted_dir.mkdir()
    
    with patch('app.crypto.crypto.ENCRYPTED_DIR', encrypted_dir):
        with patch('app.crypto.crypto.PRIVATE_KEY_PATH', tmp_path / "nonexistent.key"):
            with pytest.raises(RuntimeError, match="Старый приватный ключ не найден"):
                await crypto.rotate_keys()


@pytest.mark.asyncio
async def test_reencrypt_file_nonexistent(tmp_path):
    """Тест перешифрования несуществующего файла"""
    crypto = CryptoManager()
    
    # Функция должна просто возвращаться если файл не существует
    await crypto.reencrypt_file(
        tmp_path / "nonexistent.age",
        tmp_path / "old.key",
        "age1newkey"
    )
    # Не должно быть исключения


@pytest.mark.asyncio
async def test_reencrypt_file_not_file(tmp_path):
    """Тест перешифрования когда путь - не файл"""
    crypto = CryptoManager()
    
    # Создаем директорию вместо файла
    directory = tmp_path / "directory"
    directory.mkdir()
    
    # Функция должна просто возвращаться если это не файл
    await crypto.reencrypt_file(
        directory,
        tmp_path / "old.key",
        "age1newkey"
    )
    # Не должно быть исключения


if __name__ == "__main__":
    pytest.main([__file__])
