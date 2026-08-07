"""认证 API 测试 - 注册/登录/鉴权/用户隔离"""


def test_register_success(app_client):
    resp = app_client.post("/api/v1/auth/register",
                           json={"username": "bob", "password": "secret123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "bob"
    assert "id" in body


def test_register_duplicate_username(app_client):
    app_client.post("/api/v1/auth/register",
                    json={"username": "bob", "password": "secret123"})
    resp = app_client.post("/api/v1/auth/register",
                           json={"username": "bob", "password": "other456"})
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]


def test_register_short_password(app_client):
    resp = app_client.post("/api/v1/auth/register",
                           json={"username": "bob", "password": "123"})
    assert resp.status_code == 422


def test_login_success_and_me(app_client, auth_headers):
    resp = app_client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_login_wrong_password(app_client):
    app_client.post("/api/v1/auth/register",
                    json={"username": "bob", "password": "secret123"})
    resp = app_client.post("/api/v1/auth/login",
                           json={"username": "bob", "password": "wrongpass"})
    assert resp.status_code == 401


def test_me_without_token(app_client):
    resp = app_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token(app_client):
    resp = app_client.get("/api/v1/auth/me",
                          headers={"Authorization": "Bearer bad.token.value"})
    assert resp.status_code == 401
