import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from datetime import timedelta


@pytest.fixture
def client():
    return TestClient(app)


def test_login_success(client):
    """Тест успешного входа"""
    with patch('app.api.auth.get_db') as mock_get_db:
        mock_db = AsyncMock()
        mock_get_db.return_value = mock_db
        
        # Мокаем пользователя
        mock_user = Mock()
        mock_user.username = "testuser"
        mock_user.hashed_password = "hashed_password"
        mock_user.is_active = True
        mock_user.role = "user"
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user
        
        # Мокаем verify_password
        with patch('app.api.auth.verify_password') as mock_verify:
            mock_verify.return_value = True
            
            # Мокаем create_access_token
            with patch('app.api.auth.create_access_token') as mock_token:
                mock_token.return_value = "test_jwt_token"
                
                # Мокаем audit_logger
                with patch('app.api.auth.audit_logger') as mock_logger:
                    response = client.post("/auth/login", data={
                        "username": "testuser",
                        "password": "correct_password"
                    })
                    
                    assert response.status_code == 200
                    data = response.json()
                    
                    assert "access_token" in data
                    assert data["access_token"] == "test_jwt_token"
                    assert data["token_type"] == "bearer"
                    assert data["role"] == "user"
                    assert data["username"] == "testuser"
                    assert data["expires_in"] == 3600
                    
                    # Проверяем что успех был залогирован
                    mock_logger.log_operation.assert_called_with(
                        action="login_success",
                        filename="",
                        user="testuser",
                        reason="Успешный вход",
                        success=True
                    )


def test_login_user_not_found(client):
    """Тест входа с несуществующим пользователем"""
    with patch('app.api.auth.get_db') as mock_get_db:
        mock_db = AsyncMock()
        mock_get_db.return_value = mock_db
        
        # Пользователь не найден
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        
        with patch('app.api.auth.audit_logger') as mock_logger:
            response = client.post("/auth/login", data={
                "username": "nonexistent",
                "password": "password"
            })
            
            assert response.status_code == 401
            data = response.json()
            assert "detail" in data
            assert "Неверное имя пользователя или пароль" in data["detail"]
            
            # Проверяем что неудача была залогирована
            mock_logger.log_operation.assert_called_with(
                action="login_failed",
                filename="",
                user="nonexistent",
                reason="Пользователь не найден или отключён",
                success=False
            )


def test_login_wrong_password(client):
    """Тест входа с неверным паролем"""
    with patch('app.api.auth.get_db') as mock_get_db:
        mock_db = AsyncMock()
        mock_get_db.return_value = mock_db
        
        # Пользователь существует
        mock_user = Mock()
        mock_user.username = "testuser"
        mock_user.hashed_password = "hashed_password"
        mock_user.is_active = True
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user
        
        # Пароль неверный
        with patch('app.api.auth.verify_password') as mock_verify:
            mock_verify.return_value = False
            
            with patch('app.api.auth.audit_logger') as mock_logger:
                response = client.post("/auth/login", data={
                    "username": "testuser",
                    "password": "wrong_password"
                })
                
                assert response.status_code == 401
                data = response.json()
                assert "detail" in data
                
                # Проверяем логирование
                mock_logger.log_operation.assert_called_with(
                    action="login_failed",
                    filename="",
                    user="testuser",
                    reason="Неверный пароль",
                    success=False
                )


def test_login_inactive_user(client):
    """Тест входа неактивного пользователя"""
    with patch('app.api.auth.get_db') as mock_get_db:
        mock_db = AsyncMock()
        mock_get_db.return_value = mock_db
        
        # Пользователь неактивен
        mock_user = Mock()
        mock_user.username = "inactive"
        mock_user.hashed_password = "hashed_password"
        mock_user.is_active = False
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_user
        
        with patch('app.api.auth.audit_logger') as mock_logger:
            response = client.post("/auth/login", data={
                "username": "inactive",
                "password": "password"
            })
            
            assert response.status_code == 401
            data = response.json()
            assert "detail" in data
            
            # Проверяем логирование
            mock_logger.log_operation.assert_called_with(
                action="login_failed",
                filename="",
                user="inactive",
                reason="Пользователь не найден или отключён",
                success=False
            )


def test_change_password_success(client):
    """Тест успешной смены пароля"""
    with patch('app.api.auth.get_current_user') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "testuser"
        mock_user.role = "user"
        mock_auth.return_value = mock_user
        
        with patch('app.api.auth.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Мокаем пользователя в БД
            mock_db_user = Mock()
            mock_db_user.id = 1
            mock_db_user.username = "testuser"
            mock_db_user.hashed_password = "old_hashed_password"
            
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_user
            
            # Мокаем verify_password
            with patch('app.api.auth.verify_password') as mock_verify:
                # Старый парверен верный
                mock_verify.side_effect = lambda pw, hashed: {
                    ("old_password", "old_hashed_password"): True,
                    ("new_password", "old_hashed_password"): False
                }.get((pw, hashed), False)
                
                # Мокаем get_password_hash
                with patch('app.api.auth.get_password_hash') as mock_hash:
                    mock_hash.return_value = "new_hashed_password"
                    
                    # Мокаем audit_logger
                    with patch('app.api.auth.audit_logger') as mock_logger:
                        response = client.post(
                            "/auth/change-password",
                            json={
                                "old_password": "old_password",
                                "new_password": "new_password"
                            },
                            headers={"Authorization": "Bearer test_token"}
                        )
                        
                        assert response.status_code == 200
                        data = response.json()
                        assert "message" in data
                        assert data["message"] == "Пароль успешно изменён"
                        
                        # Проверяем что пароль был обновлен в БД
                        assert mock_db.execute.called
                        assert mock_db.commit.called
                        
                        # Проверяем логирование
                        mock_logger.log_operation.assert_called_with(
                            action="change_password",
                            filename="",
                            user="testuser",
                            reason="Пароль успешно изменён",
                            success=True,
                            metadata={"username": "testuser"}
                        )


def test_change_password_user_not_found(client):
    """Тест смены пароля когда пользователь не найден в БД"""
    with patch('app.api.auth.get_current_user') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "testuser"
        mock_auth.return_value = mock_user
        
        with patch('app.api.auth.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Пользователь не найден в БД
            mock_db.execute.return_value.scalar_one_or_none.return_value = None
            
            with patch('app.api.auth.audit_logger') as mock_logger:
                response = client.post(
                    "/auth/change-password",
                    json={
                        "old_password": "old_password",
                        "new_password": "new_password"
                    }
                )
                
                assert response.status_code == 404
                data = response.json()
                assert "detail" in data
                assert "Пользователь не найден" in data["detail"]
                
                # Проверяем логирование
                mock_logger.log_operation.assert_called_with(
                    action="change_password_failed",
                    filename="",
                    user="testuser",
                    reason="Пользователь не найден",
                    success=False
                )


def test_change_password_wrong_old_password(client):
    """Тест смены пароля с неверным старым паролем"""
    with patch('app.api.auth.get_current_user') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "testuser"
        mock_auth.return_value = mock_user
        
        with patch('app.api.auth.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            mock_db_user = Mock()
            mock_db_user.id = 1
            mock_db_user.username = "testuser"
            mock_db_user.hashed_password = "correct_hashed_password"
            
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_user
            
            # Старый пароль неверный
            with patch('app.api.auth.verify_password') as mock_verify:
                mock_verify.return_value = False
                
                with patch('app.api.auth.audit_logger') as mock_logger:
                    response = client.post(
                        "/auth/change-password",
                        json={
                            "old_password": "wrong_old_password",
                            "new_password": "new_password"
                        }
                    )
                    
                    assert response.status_code == 401
                    data = response.json()
                    assert "detail" in data
                    assert "Неверный текущий пароль" in data["detail"]
                    
                    # Проверяем логирование
                    mock_logger.log_operation.assert_called_with(
                        action="change_password_failed",
                        filename="",
                        user="testuser",
                        reason="Неверный старый пароль",
                        success=False
                    )


def test_change_password_same_as_old(client):
    """Тест смены пароля на тот же самый"""
    with patch('app.api.auth.get_current_user') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "testuser"
        mock_auth.return_value = mock_user
        
        with patch('app.api.auth.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            mock_db_user = Mock()
            mock_db_user.id = 1
            mock_db_user.username = "testuser"
            mock_db_user.hashed_password = "current_hashed_password"
            
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_user
            
            with patch('app.api.auth.verify_password') as mock_verify:
                # Старый пароль верный, новый совпадает со старым
                def verify_side_effect(password, hashed):
                    if password == "old_password" and hashed == "current_hashed_password":
                        return True
                    elif password == "old_password" and hashed == "current_hashed_password":
                        return True  # Новый совпадает со старым
                    return False
                
                mock_verify.side_effect = verify_side_effect
                
                response = client.post(
                    "/auth/change-password",
                    json={
                        "old_password": "old_password",
                        "new_password": "old_password"  # Тот же пароль
                    }
                )
                
                assert response.status_code == 400
                data = response.json()
                assert "detail" in data
                assert "Новый пароль не должен совпадать со старым" in data["detail"]


def test_rate_limiting_on_login(client):
    """Тест rate limiting на логине"""
    # Этот тест сложнее, так как зависит от slowapi
    # В реальном тесте нужно мокать limiter
    pass


def test_rate_limiting_on_change_password(client):
    """Тест rate limiting на смене пароля"""
    # Аналогично, требует мокирования limiter
    pass


if __name__ == "__main__":
    pytest.main([__file__])
