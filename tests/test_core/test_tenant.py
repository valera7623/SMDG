import pytest
from fastapi import HTTPException

from app.core.tenant import extract_subdomain, assert_tenant_access


def test_extract_subdomain_success():
    assert extract_subdomain("clinic-a.smdg.local") == "clinic-a"
    assert extract_subdomain("clinic-a.smdg.local:8000") == "clinic-a"


def test_extract_subdomain_none_for_root_domain():
    assert extract_subdomain("smdg.local") is None
    assert extract_subdomain("localhost:8000") is None


def test_extract_subdomain_localhost_dev():
    """Два сегмента alpha.localhost — поддомен alpha (curl / dev)."""
    assert extract_subdomain("alpha.localhost") == "alpha"
    assert extract_subdomain("alpha.localhost:8000") == "alpha"


def test_assert_tenant_access_forbidden():
    with pytest.raises(HTTPException) as exc:
        assert_tenant_access(current_user_tenant_id=1, request_tenant_id=2, role="admin")
    assert exc.value.status_code == 403


def test_assert_tenant_access_super_admin():
    assert_tenant_access(current_user_tenant_id=1, request_tenant_id=2, role="super_admin")
