import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'], DEBUG=True)
def test_admin_login_page_shows_form(client):
    """Cloudflare Access middleware skips validation when DEBUG=True."""
    response = client.get('/admin/login/')
    assert response.status_code == 200
    content = response.content.decode()
    assert 'name="username"' in content
    assert 'name="password"' in content
