"""Nanini's Café - API de pedidos (FastAPI + SQLAlchemy + PostgreSQL)."""
import base64
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

import csv
import io

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv(override=True)  # o .env da pasta do backend sempre vence, mesmo se o Windows já tiver essas variáveis
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text, create_engine, func)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

# ---------- Configuração (defina no painel do Render/Railway) ----------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./naninis.db")  # use a URL do Supabase em produção
SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@naninis.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "trocar123")
STATUSES = ["recebido", "preparando", "pronto", "entregue", "cancelado"]
STATUS_PT = {"recebido": "Recebido", "preparando": "Preparando", "pronto": "Pronto",
             "entregue": "Entregue", "cancelado": "Cancelado"}

# Supabase Storage (upload de fotos dos produtos)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # ex.: https://xxxx.supabase.co
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key (NUNCA a anon key)
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "product-images")
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

engine = create_engine(DATABASE_URL)
Session_ = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()
pwd = CryptContext(schemes=["bcrypt"])
oauth2 = OAuth2PasswordBearer(tokenUrl="auth/login")


# ---------- Modelos ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    price = Column(Float, nullable=False)
    image_url = Column(Text, default="")
    active = Column(Boolean, default=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="products")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    customer_name = Column(String, nullable=False)
    order_type = Column(String, default="local")  # "local" ou "viagem"
    table_number = Column(String, default="")
    phone = Column(String, default="")
    notes = Column(Text, default="")
    status = Column(String, default="recebido")
    total = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)  # preço congelado no momento do pedido
    order = relationship("Order", back_populates="items")
    product = relationship("Product")


# ---------- Schemas ----------
class ProductIn(BaseModel):
    name: str
    description: str = ""
    price: float = Field(gt=0)
    image_url: str = ""
    active: bool = True
    category_id: Optional[int] = None


class ItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=50)


class OrderIn(BaseModel):
    customer_name: str = Field(min_length=1)
    order_type: str = Field(default="local", pattern="^(local|viagem)$")
    table_number: str = ""
    phone: str = ""
    notes: str = ""
    items: list[ItemIn] = Field(min_length=1)


class StatusIn(BaseModel):
    status: str


class UploadIn(BaseModel):
    filename: str
    content_base64: str  # sem o prefixo "data:image/...;base64,"
    content_type: str = "image/jpeg"


# ---------- App ----------
app = FastAPI(title="Nanini's Café API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_db():
    db = Session_()
    try:
        yield db
    finally:
        db.close()


def staff(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        email = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])["sub"]
    except (JWTError, KeyError):
        raise HTTPException(401, "Sessão inválida")
    user = db.query(User).filter_by(email=email).first()
    if not user:
        raise HTTPException(401, "Usuário não encontrado")
    return user


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    db = Session_()
    if not db.query(User).first():
        db.add(User(email=ADMIN_EMAIL, password_hash=pwd.hash(ADMIN_PASSWORD)))
        db.add_all([Category(name=n) for n in ["Cafés", "Bebidas", "Lanches", "Doces"]])
        db.commit()
    db.close()


def order_dict(o: Order):
    return {"id": o.id, "customer_name": o.customer_name, "order_type": o.order_type, "table_number": o.table_number, "phone": o.phone,
            "notes": o.notes, "status": o.status, "total": o.total, "created_at": o.created_at,
            "items": [{"name": i.product.name, "quantity": i.quantity, "unit_price": i.unit_price}
                      for i in o.items]}


# ---------- Autenticação ----------
@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=form.username).first()
    if not user or not pwd.verify(form.password, user.password_hash):
        raise HTTPException(401, "E-mail ou senha incorretos")
    exp = datetime.utcnow() + timedelta(hours=12)
    token = jwt.encode({"sub": user.email, "exp": exp}, SECRET_KEY, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer"}


# ---------- Cliente (público) ----------
@app.get("/menu")
def menu(db: Session = Depends(get_db)):
    cats = db.query(Category).all()
    return [{"id": c.id, "name": c.name,
             "products": [{"id": p.id, "name": p.name, "description": p.description,
                           "price": p.price, "image_url": p.image_url}
                          for p in c.products if p.active]} for c in cats]


@app.post("/orders", status_code=201)
def create_order(data: OrderIn, db: Session = Depends(get_db)):
    order = Order(customer_name=data.customer_name, order_type=data.order_type, notes=data.notes,
                  table_number=data.table_number if data.order_type == "local" else "", phone=data.phone)
    total = 0.0
    for it in data.items:
        p = db.get(Product, it.product_id)
        if not p or not p.active:
            raise HTTPException(400, f"Produto {it.product_id} indisponível")
        order.items.append(OrderItem(product_id=p.id, quantity=it.quantity, unit_price=p.price))
        total += p.price * it.quantity
    order.total = round(total, 2)
    db.add(order)
    db.commit()
    return {"id": order.id, "status": order.status, "total": order.total}


@app.get("/orders/{order_id}/status")
def order_status(order_id: int, db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Pedido não encontrado")
    return {"id": o.id, "status": o.status}


# ---------- Equipe (protegido) ----------
def _apply_order_filters(q, status: Optional[str], start_date: Optional[str], end_date: Optional[str]):
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        q = q.filter(Order.status.in_(statuses)) if len(statuses) > 1 else q.filter(Order.status == statuses[0])
    if start_date:
        q = q.filter(Order.created_at >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        q = q.filter(Order.created_at < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1))
    return q


@app.get("/staff/orders")
def list_orders(status: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None,
                 page: int = 1, page_size: int = 20, db: Session = Depends(get_db), _=Depends(staff)):
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    q = _apply_order_filters(db.query(Order).order_by(Order.created_at.desc()), status, start_date, end_date)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [order_dict(o) for o in items], "total": total, "page": page,
        "page_size": page_size, "pages": max(1, -(-total // page_size)),
    }


@app.get("/staff/orders/export")
def export_orders(status: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None,
                   db: Session = Depends(get_db), _=Depends(staff)):
    q = _apply_order_filters(db.query(Order).order_by(Order.created_at.desc()), status, start_date, end_date)
    orders = q.all()

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM: acentos corretos ao abrir no Excel
    w = csv.writer(buf, delimiter=";")
    w.writerow(["pedido_id", "data_hora", "cliente", "tipo", "mesa", "telefone", "status", "itens", "total"])
    for o in orders:
        itens = "; ".join(f"{i.quantity}x {i.product.name}" for i in o.items)
        w.writerow([o.id, o.created_at.strftime("%Y-%m-%d %H:%M"), o.customer_name,
                    "Comer no local" if o.order_type == "local" else "Para levar",
                    o.table_number, o.phone, STATUS_PT.get(o.status, o.status), itens, f"{o.total:.2f}".replace(".", ",")])

    filename = f"pedidos_naninis_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                              headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.patch("/staff/orders/{order_id}")
def set_status(order_id: int, data: StatusIn, db: Session = Depends(get_db), _=Depends(staff)):
    if data.status not in STATUSES:
        raise HTTPException(400, "Status inválido")
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Pedido não encontrado")
    o.status = data.status
    db.commit()
    return order_dict(o)


@app.get("/staff/products")
def staff_products(db: Session = Depends(get_db), _=Depends(staff)):
    return db.query(Product).order_by(Product.name).all()


@app.post("/staff/products", status_code=201)
def add_product(data: ProductIn, db: Session = Depends(get_db), _=Depends(staff)):
    p = Product(**data.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id}


@app.put("/staff/products/{pid}")
def edit_product(pid: int, data: ProductIn, db: Session = Depends(get_db), _=Depends(staff)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Produto não encontrado")
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return {"ok": True}


@app.post("/staff/uploads")
def upload_image(data: UploadIn, _=Depends(staff)):
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(500, "Upload não configurado: defina SUPABASE_URL e SUPABASE_SERVICE_KEY no servidor")
    ext = ALLOWED_IMAGE_TYPES.get(data.content_type)
    if not ext:
        raise HTTPException(400, "Formato de imagem não suportado (use jpg, png, webp ou heic)")
    try:
        raw = base64.b64decode(data.content_base64, validate=True)
    except Exception:
        raise HTTPException(400, "Conteúdo da imagem inválido")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "Imagem maior que 5 MB")

    path = f"products/{uuid.uuid4().hex}.{ext}"
    put_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path}"
    r = requests.put(
        put_url, data=raw, timeout=30,
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": data.content_type,
            "x-upsert": "true",
        },
    )
    if r.status_code not in (200, 201):
        raise HTTPException(502, f"Falha ao enviar para o Supabase: {r.text[:200]}")

    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{path}"
    return {"url": public_url}


@app.get("/staff/dashboard")
def dashboard(days: int = 7, start_date: Optional[str] = None, end_date: Optional[str] = None,
              db: Session = Depends(get_db), _=Depends(staff)):
    if start_date:
        since = datetime.strptime(start_date, "%Y-%m-%d")
        until = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)) if end_date else datetime.utcnow()
        valid = (Order.created_at >= since, Order.created_at < until, Order.status != "cancelado")
    else:
        since = datetime.utcnow() - timedelta(days=days)
        valid = (Order.created_at >= since, Order.status != "cancelado")
    revenue, count = db.query(func.coalesce(func.sum(Order.total), 0), func.count(Order.id)).filter(*valid).one()
    top = (db.query(Product.name, func.sum(OrderItem.quantity).label("qty"),
                    func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue"))
           .join(OrderItem, OrderItem.product_id == Product.id)
           .join(Order, Order.id == OrderItem.order_id)
           .filter(*valid).group_by(Product.name).order_by(func.sum(OrderItem.quantity).desc()).limit(5).all())
    by_day = (db.query(func.date(Order.created_at).label("day"), func.sum(Order.total), func.count(Order.id))
              .filter(*valid).group_by("day").order_by("day").all())
    by_status = dict(db.query(Order.status, func.count(Order.id)).filter(Order.created_at >= since)
                     .group_by(Order.status).all())
    return {"since": str(since.date()), "revenue": round(revenue, 2), "orders": count,
            "avg_ticket": round(revenue / count, 2) if count else 0,
            "top_products": [{"name": n, "quantity": int(q), "revenue": round(r, 2)} for n, q, r in top],
            "daily": [{"day": str(d), "revenue": round(r, 2), "orders": c} for d, r, c in by_day],
            "by_status": by_status}
