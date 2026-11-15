"""Configuração compartilhada dos testes: cada teste roda com um banco SQLite
próprio (arquivo temporário), isolado do banco de desenvolvimento/produção."""
import importlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test_naninis.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("SECRET_KEY", "chave-de-teste")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@teste.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-teste-123")

    import main as main_module
    importlib.reload(main_module)  # garante que o módulo leia as variáveis de ambiente acima

    from fastapi.testclient import TestClient
    with TestClient(main_module.app) as test_client:
        test_client.main_module = main_module  # facilita acessar STATUSES etc. quando precisar
        yield test_client


@pytest.fixture
def staff_token(client):
    r = client.post("/auth/login", data={"username": "admin@teste.com", "password": "senha-teste-123"})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(staff_token):
    return {"Authorization": f"Bearer {staff_token}"}


@pytest.fixture
def category_id(client, auth_headers):
    menu = client.get("/menu").json()
    return menu[0]["id"]


@pytest.fixture
def product_id(client, auth_headers, category_id):
    r = client.post("/staff/products", json={
        "name": "Café Coado 300ml", "description": "Grãos torrados na casa",
        "price": 8.5, "image_url": "", "active": True, "category_id": category_id,
    }, headers=auth_headers)
    assert r.status_code == 201
    return r.json()["id"]
