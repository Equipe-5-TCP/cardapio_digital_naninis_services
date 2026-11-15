def test_criar_pedido_calcula_o_total_corretamente(client, product_id):
    r = client.post("/orders", json={
        "customer_name": "Maria", "order_type": "local", "table_number": "5",
        "items": [{"product_id": product_id, "quantity": 3}],
    })
    assert r.status_code == 201
    body = r.json()
    assert body["total"] == 25.5  # 3 x 8.50
    assert body["status"] == "recebido"


def test_pedido_para_levar_nao_exige_mesa(client, product_id):
    r = client.post("/orders", json={
        "customer_name": "João", "order_type": "viagem",
        "items": [{"product_id": product_id, "quantity": 1}],
    })
    assert r.status_code == 201


def test_pedido_com_produto_inexistente_e_rejeitado(client):
    r = client.post("/orders", json={
        "customer_name": "Maria", "order_type": "local", "table_number": "5",
        "items": [{"product_id": 99999, "quantity": 1}],
    })
    assert r.status_code == 400


def test_pedido_com_produto_pausado_e_rejeitado(client, auth_headers, product_id):
    client.put(f"/staff/products/{product_id}", json={
        "name": "Café Coado 300ml", "price": 8.5, "active": False, "category_id": None,
    }, headers=auth_headers)
    r = client.post("/orders", json={
        "customer_name": "Maria", "order_type": "local", "table_number": "5",
        "items": [{"product_id": product_id, "quantity": 1}],
    })
    assert r.status_code == 400


def test_pedido_sem_nenhum_item_e_rejeitado(client):
    r = client.post("/orders", json={"customer_name": "Maria", "order_type": "local", "table_number": "5", "items": []})
    assert r.status_code == 422


def test_consultar_status_de_pedido_existente(client, product_id):
    created = client.post("/orders", json={
        "customer_name": "Maria", "order_type": "local", "table_number": "5",
        "items": [{"product_id": product_id, "quantity": 1}],
    }).json()
    r = client.get(f"/orders/{created['id']}/status")
    assert r.status_code == 200
    assert r.json()["status"] == "recebido"


def test_consultar_status_de_pedido_inexistente_retorna_404(client):
    r = client.get("/orders/99999/status")
    assert r.status_code == 404


def test_avancar_status_do_pedido(client, auth_headers, product_id):
    order_id = client.post("/orders", json={
        "customer_name": "Maria", "order_type": "local", "table_number": "5",
        "items": [{"product_id": product_id, "quantity": 1}],
    }).json()["id"]

    for novo_status in ["preparando", "pronto", "entregue"]:
        r = client.patch(f"/staff/orders/{order_id}", json={"status": novo_status}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["status"] == novo_status


def test_status_invalido_e_rejeitado(client, auth_headers, product_id):
    order_id = client.post("/orders", json={
        "customer_name": "Maria", "order_type": "local", "table_number": "5",
        "items": [{"product_id": product_id, "quantity": 1}],
    }).json()["id"]
    r = client.patch(f"/staff/orders/{order_id}", json={"status": "voando"}, headers=auth_headers)
    assert r.status_code == 400
