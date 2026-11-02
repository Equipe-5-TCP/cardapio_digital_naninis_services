def _criar_pedido(client, product_id, quantity=1):
    return client.post("/orders", json={
        "customer_name": "Cliente Teste", "order_type": "local", "table_number": "1",
        "items": [{"product_id": product_id, "quantity": quantity}],
    }).json()


def test_paginacao_retorna_metadados_corretos(client, auth_headers, product_id):
    for _ in range(5):
        _criar_pedido(client, product_id)

    r = client.get("/staff/orders?page=1&page_size=2", headers=auth_headers)
    body = r.json()
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2

    r2 = client.get("/staff/orders?page=3&page_size=2", headers=auth_headers)
    assert len(r2.json()["items"]) == 1  # última página com o resto


def test_filtro_por_status_combinado_funciona_na_listagem(client, auth_headers, product_id):
    id1 = _criar_pedido(client, product_id)["id"]
    _criar_pedido(client, product_id)
    client.patch(f"/staff/orders/{id1}", json={"status": "preparando"}, headers=auth_headers)

    r = client.get("/staff/orders?status=recebido,preparando", headers=auth_headers)
    assert r.json()["total"] == 2


def test_exportar_csv_contem_cabecalho_e_pedido(client, auth_headers, product_id):
    _criar_pedido(client, product_id, quantity=2)
    r = client.get("/staff/orders/export", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    content = r.content.decode("utf-8-sig")
    assert "pedido_id" in content
    assert "Cliente Teste" in content


def test_dashboard_calcula_faturamento_e_ticket_medio(client, auth_headers, product_id):
    _criar_pedido(client, product_id, quantity=2)  # 17.00
    _criar_pedido(client, product_id, quantity=1)  # 8.50

    r = client.get("/staff/dashboard?days=7", headers=auth_headers)
    body = r.json()
    assert body["orders"] == 2
    assert body["revenue"] == 25.5
    assert body["avg_ticket"] == 12.75


def test_dashboard_top_produtos_ordena_por_quantidade(client, auth_headers, product_id):
    _criar_pedido(client, product_id, quantity=5)
    r = client.get("/staff/dashboard?days=7", headers=auth_headers)
    top = r.json()["top_products"]
    assert top[0]["name"] == "Café Coado 300ml"
    assert top[0]["quantity"] == 5


def test_dashboard_sem_pedidos_nao_quebra(client, auth_headers):
    r = client.get("/staff/dashboard?days=7", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["revenue"] == 0
    assert r.json()["avg_ticket"] == 0
