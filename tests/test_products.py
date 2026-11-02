def test_categorias_padrao_sao_criadas_no_primeiro_start(client):
    menu = client.get("/menu").json()
    nomes = [c["name"] for c in menu]
    assert "Cafés" in nomes and "Bebidas" in nomes


def test_cardapio_publico_nao_lista_produto_inativo(client, auth_headers, category_id):
    client.post("/staff/products", json={
        "name": "Produto Pausado", "price": 5, "active": False, "category_id": category_id,
    }, headers=auth_headers)
    menu = client.get("/menu").json()
    todos_nomes = [p["name"] for c in menu for p in c["products"]]
    assert "Produto Pausado" not in todos_nomes


def test_criar_produto_sem_autenticacao_e_rejeitado(client, category_id):
    r = client.post("/staff/products", json={"name": "Café", "price": 8.5, "category_id": category_id})
    assert r.status_code == 401


def test_criar_produto_com_preco_invalido_e_rejeitado(client, auth_headers, category_id):
    r = client.post("/staff/products", json={"name": "Café", "price": 0, "category_id": category_id}, headers=auth_headers)
    assert r.status_code == 422  # price precisa ser > 0 (Field(gt=0) no schema)


def test_editar_produto_atualiza_preco_no_cardapio(client, auth_headers, product_id):
    r = client.put(f"/staff/products/{product_id}", json={
        "name": "Café Coado 300ml", "description": "Grãos torrados na casa",
        "price": 9.5, "image_url": "", "active": True, "category_id": None,
    }, headers=auth_headers)
    assert r.status_code == 200
    menu = client.get("/menu").json()
    produto = next(p for c in menu for p in c["products"] if p["name"] == "Café Coado 300ml")
    assert produto["price"] == 9.5


def test_editar_produto_inexistente_retorna_404(client, auth_headers, category_id):
    r = client.put("/staff/products/9999", json={
        "name": "X", "price": 1, "category_id": category_id,
    }, headers=auth_headers)
    assert r.status_code == 404
