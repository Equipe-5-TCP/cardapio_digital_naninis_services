def test_login_com_senha_errada_retorna_401(client):
    r = client.post("/auth/login", data={"username": "admin@teste.com", "password": "errada"})
    assert r.status_code == 401


def test_login_com_sucesso_retorna_token(client):
    r = client.post("/auth/login", data={"username": "admin@teste.com", "password": "senha-teste-123"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_rota_da_equipe_sem_token_e_rejeitada(client):
    r = client.get("/staff/orders")
    assert r.status_code == 401


def test_rota_da_equipe_com_token_invalido_e_rejeitada(client):
    r = client.get("/staff/orders", headers={"Authorization": "Bearer token-invalido"})
    assert r.status_code == 401


def test_rota_da_equipe_com_token_valido_funciona(client, auth_headers):
    r = client.get("/staff/orders", headers=auth_headers)
    assert r.status_code == 200
