import pytest
from pathlib import Path
from app.core.utils import sanitize_filename, calculate_hash, check_path_exists


def test_sanitize_filename_fixed():
    """Исправленный тест очистки имени файла"""
    test_cases = [
        ("normal_file.pdf", "normal_file.pdf"),
        ("file with spaces.txt", "file_with_spaces.txt"),
        ("../../etc/passwd", "passwd"),
        ("file*with?special<chars>.txt", "file_with_special_chars_.txt"),
        ("ВОПРОС.docx", "VOPROS.docx"),
        ("  trimmed  .pdf", "trimmed_.pdf"),
        ("", "unknown_file"),
    ]

    for input_name, expected in test_cases:
        result = sanitize_filename(input_name)
        assert result == expected, f"Для '{input_name}' ожидалось '{expected}', получено '{result}'"


def test_sanitize_filename_edge_cases():
    """Тест крайних случаев sanitize_filename"""
    # Тест пустой строки
    assert sanitize_filename("") == "unknown_file"
    
    # Тест очень длинного имени
    long_name = "a" * 300 + ".txt"
    result = sanitize_filename(long_name)
    assert len(result) < 210  # Имя + расширение
    assert result.endswith(".txt")
    
    # Тест только специальных символов
    assert sanitize_filename("***.txt") == "_.txt"  # Исправлено
    
    # Тест с путем
    assert sanitize_filename("/path/to/file.txt") == "file.txt"
    assert sanitize_filename("C:\\Windows\\file.txt") == "file.txt"
    
    # Тест с только подчеркиваниями
    assert sanitize_filename("___.txt") == "_.txt"
    assert sanitize_filename("__") == "unknown_file"


def test_calculate_hash():
    """Тест расчета хеша файла"""
    test_file = Path("test_hash.txt")
    test_file.write_text("test content")
    
    try:
        hash_result = calculate_hash(test_file)
        assert len(hash_result) == 64
        assert not hash_result.startswith("hash_error:")
    finally:
        test_file.unlink()


def test_calculate_hash_nonexistent_fixed():
    """Тест расчета хеша несуществующего файла"""
    hash_result = calculate_hash(Path("nonexistent_file.txt"))
    assert "hash_error" in hash_result
    assert "file_not_found" in hash_result


def test_calculate_hash_different_algorithms():
    """Тест расчета хеша с разными алгоритмами"""
    test_file = Path("test_hash_algo.txt")
    test_file.write_text("test")
    
    try:
        md5_hash = calculate_hash(test_file, algorithm="md5")
        assert len(md5_hash) == 32
        
        sha1_hash = calculate_hash(test_file, algorithm="sha1")
        assert len(sha1_hash) == 40
        
        sha256_hash = calculate_hash(test_file)
        assert len(sha256_hash) == 64
    finally:
        test_file.unlink()


def test_check_path_exists():
    """Тест проверки существования пути"""
    test_file = Path("test_exists.txt")
    test_file.write_text("test")
    
    try:
        assert check_path_exists(test_file) == True
        assert check_path_exists(Path("nonexistent.txt")) == False
        assert check_path_exists(Path.cwd()) == True
    finally:
        test_file.unlink()
        
        
# tests/test_utils.py (дополнение)
import pytest
from pathlib import Path
import tempfile
import shutil
from app.core.utils import calculate_hash


class TestCalculateHash:
    """Тесты для функции calculate_hash"""
    
    def test_calculate_hash_empty_file(self):
        """Тест вычисления хеша пустого файла"""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            hash_value = calculate_hash(tmp_path)
            # Хеш пустого файла SHA256
            assert hash_value == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        finally:
            tmp_path.unlink()
    
    def test_calculate_hash_large_file(self):
        """Тест вычисления хеша большого файла"""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            # Записываем 2MB данных
            data = b"x" * (2 * 1024 * 1024)
            tmp.write(data)
            tmp_path = Path(tmp.name)
        
        try:
            hash_value = calculate_hash(tmp_path)
            assert len(hash_value) == 64
            # Проверяем что функция не падает на больших файлах
        finally:
            tmp_path.unlink()
    
    def test_calculate_hash_nonexistent_file(self):
        """Тест вычисления хеша несуществующего файла"""
        with pytest.raises(FileNotFoundError):
            calculate_hash(Path("/nonexistent/path/file.txt"))


if __name__ == "__main__":
    pytest.main([__file__])
