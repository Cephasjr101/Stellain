"""
Stellain — Backend API
Database: Firebase Firestore (if configured) with automatic SQLite fallback.
Auth:     Firebase Auth ID tokens (if configured) with ADMIN_TOKEN fallback.

Render start command: uvicorn main:app --host 0.0.0.0 --port $PORT
Env vars:
  ADMIN_TOKEN              - fallback admin token (default demo-token-123 — CHANGE IT)
  FIREBASE_SERVICE_ACCOUNT - service account JSON (one line) — enables Firestore, Storage, Auth verify
  FIREBASE_STORAGE_BUCKET  - optional, defaults to <project>.appspot.com
"""
import os, time, shutil, json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3

DB = "shop.db"
UPLOAD_DIR = "uploads"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "Stellarock")

# ---------------- Firebase init (optional) ----------------
firestore_client = None
storage_bucket = None
firebase_auth = None
if os.getenv("FIREBASE_SERVICE_ACCOUNT") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    try:
        from google.cloud import firestore, storage as gcs
        if os.getenv("FIREBASE_SERVICE_ACCOUNT"):
            sa = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
            firestore_client = firestore.Client.from_service_account_info(sa)
            storage_client = gcs.Client.from_service_account_info(sa)
        else:
            firestore_client = firestore.Client()
            storage_client = gcs.Client()
        print("Connected to Firebase Firestore")
        try:
            bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", f"{storage_client.project}.appspot.com")
            storage_bucket = storage_client.bucket(bucket_name)
            storage_bucket.exists()
            print(f"Connected to Firebase Storage ({bucket_name})")
        except Exception as se:
            print(f"Storage init failed ({se}) — uploads will save locally")
    except Exception as e:
        print(f"Firebase init failed ({e}) — falling back to SQLite")

    # Firebase Admin Auth (verifies login tokens from the admin dashboard)
    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth
        if not firebase_admin._apps:
            if os.getenv("FIREBASE_SERVICE_ACCOUNT"):
                firebase_admin.initialize_app(firebase_admin.credentials.Certificate(
                    json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])))
            else:
                firebase_admin.initialize_app()
        firebase_auth = fb_auth
        print("Firebase Auth verifier ready")
    except Exception as e:
        print(f"Auth init failed ({e}) — ADMIN_TOKEN fallback active")

USE_FIREBASE = firestore_client is not None

app = FastAPI(title="Stellain API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------- seed data ----------------
SEED = [
    ("wears","Women's Ankara Print Dress",25,"Vibrant prints, sizes S–XXL. Bulk discount from 10 pcs."),
    ("wears","Bodycon Midi Dress (3-Pack)",30,"Assorted colors, stretch fabric. Wholesale friendly."),
    ("cosmetics","Matte Lipstick Set (12 Colors)",12,"Long-lasting, smudge-proof. Beauty salon quality."),
    ("cosmetics","Vitamin C Serum + Moisturizer Kit",18,"Brightening skincare duo. Sealed & certified."),
    ("utensils","Non-Stick Cookware Set (10-Piece)",55,"Pots, pans & lids. Gas & induction compatible."),
    ("utensils","Stainless Steel Cutlery Set (24-Pc)",15,"Forks, knives, spoons for 6. Dishwasher safe."),
    ("appliances","Air Fryer 5.5L Digital",48,"Oil-free frying, touch display. 220V & 110V versions."),
    ("appliances","Blender & Juicer 2-in-1, 1.5L",35,"700W, 2 speeds + pulse. Household & commercial."),
    ("fashion","Designer Handbag (PU Leather)",22,"Trendy styles, multiple colors. MOQ 5 pcs."),
    ("fashion","Women's Sneakers — White, 36–42",28,"Casual comfort, unisex sizing. Container pricing available."),
]

def seed_firebase():
    coll = firestore_client.collection("items")
    if len(list(coll.limit(1).stream())) == 0:
        for i, (t, n, p, d) in enumerate(SEED, start=1):
            coll.document(str(i)).set({"id": i, "type": t, "name": n, "price": p, "desc": d, "img": "", "created": int(time.time())})

def sql_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_sqlite():
    conn = sql_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, name TEXT NOT NULL,
        price REAL NOT NULL, desc TEXT DEFAULT '', img TEXT DEFAULT '', created INTEGER)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, customer TEXT, phone TEXT,
        price REAL DEFAULT 0, note TEXT DEFAULT '', status TEXT DEFAULT 'new', created INTEGER)""")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(orders)")]
    if "status" not in cols:
        conn.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'new'")
    if "price" not in cols:
        conn.execute("ALTER TABLE orders ADD COLUMN price REAL DEFAULT 0")
    if conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"] == 0:
        conn.executemany("INSERT INTO items(type,name,price,desc,img,created) VALUES(?,?,?,?,?,?)",
                         [(t,n,p,d,"",int(time.time())) for t,n,p,d in SEED])
    conn.commit(); conn.close()

if USE_FIREBASE:
    seed_firebase()
else:
    init_sqlite()

# ---------------- data layer ----------------
def list_items():
    if USE_FIREBASE:
        return [{**d.to_dict()} for d in firestore_client.collection("items").order_by("created", direction="DESCENDING").stream()]
    conn = sql_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM items ORDER BY id DESC").fetchall()]
    conn.close(); return rows

def create_item(item):
    new_id = int(time.time())
    if USE_FIREBASE:
        firestore_client.collection("items").document(str(new_id)).set(
            {"id": new_id, "type": item.type, "name": item.name, "price": item.price,
             "desc": item.desc, "img": item.img, "created": int(time.time())})
    else:
        conn = sql_conn()
        conn.execute("INSERT INTO items(id,type,name,price,desc,img,created) VALUES(?,?,?,?,?,?,?)",
                     (new_id, item.type, item.name, item.price, item.desc, item.img, int(time.time())))
        conn.commit(); conn.close()
    return new_id

def update_item(item_id, item):
    if USE_FIREBASE:
        firestore_client.collection("items").document(str(item_id)).update(
            {"type": item.type, "name": item.name, "price": item.price, "desc": item.desc, "img": item.img})
    else:
        conn = sql_conn()
        conn.execute("UPDATE items SET type=?,name=?,price=?,desc=?,img=? WHERE id=?",
                     (item.type, item.name, item.price, item.desc, item.img, item_id))
        conn.commit(); conn.close()

def delete_item(item_id):
    if USE_FIREBASE:
        firestore_client.collection("items").document(str(item_id)).delete()
    else:
        conn = sql_conn()
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit(); conn.close()

def create_order(o):
    price = next((i["price"] for i in list_items() if i["name"] == o.item_name), 0)
    if USE_FIREBASE:
        oid = int(time.time() * 1000)
        firestore_client.collection("orders").document(str(oid)).set(
            {"id": oid, "item_name": o.item_name, "customer": o.customer, "phone": o.phone,
             "price": price, "note": o.note, "status": "new", "created": int(time.time())})
    else:
        conn = sql_conn()
        conn.execute("INSERT INTO orders(item_name,customer,phone,price,note,status,created) VALUES(?,?,?,?,?,?,?)",
                     (o.item_name, o.customer, o.phone, price, o.note, "new", int(time.time())))
        conn.commit(); conn.close()

def list_orders():
    if USE_FIREBASE:
        return [{**d.to_dict()} for d in firestore_client.collection("orders").order_by("created", direction="DESCENDING").stream()]
    conn = sql_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()]
    conn.close(); return rows

def set_order_status(order_id, status):
    if USE_FIREBASE:
        firestore_client.collection("orders").document(str(order_id)).update({"status": status})
    else:
        conn = sql_conn()
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        conn.commit(); conn.close()

def get_stats():
    items = list_items()
    orders = list_orders()
    week_ago = time.time() - 7 * 86400
    return {
        "total_items": len(items),
        "total_orders": len(orders),
        "orders_this_week": len([o for o in orders if o.get("created", 0) >= week_ago]),
        "order_value_total": sum(o.get("price", 0) for o in orders),
        "new_orders": len([o for o in orders if o.get("status") == "new"]),
    }

# ---------------- auth ----------------
def require_admin(authorization: str = Header(default="")):
    token = authorization.replace("Bearer", "").strip()
    if firebase_auth is not None and token:
        try:
            firebase_auth.verify_id_token(token)
            return
        except Exception:
            raise HTTPException(401, "Invalid or expired login — sign in again")
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(401, "Invalid or missing admin token")

# ---------------- models ----------------
class ItemIn(BaseModel):
    type: str
    name: str
    price: float
    desc: str = ""
    img: str = ""

class OrderIn(BaseModel):
    item_name: str
    customer: str
    phone: str
    note: str = ""

class StatusIn(BaseModel):
    status: str   # new | contacted | sold

# ---------------- public endpoints ----------------
@app.get("/api/items")
def api_list_items():
    return list_items()

@app.post("/api/orders")
def api_create_order(o: OrderIn):
    create_order(o)
    return {"ok": True}

# ---------------- admin endpoints ----------------
@app.get("/api/stats")
def api_stats(authorization: str = Header(default="")):
    require_admin(authorization)
    return get_stats()

@app.post("/api/items")
def api_create_item(item: ItemIn, authorization: str = Header(default="")):
    require_admin(authorization)
    return {"ok": True, "id": create_item(item)}

@app.put("/api/items/{item_id}")
def api_update_item(item_id: int, item: ItemIn, authorization: str = Header(default="")):
    require_admin(authorization)
    update_item(item_id, item)
    return {"ok": True}

@app.delete("/api/items/{item_id}")
def api_delete_item(item_id: int, authorization: str = Header(default="")):
    require_admin(authorization)
    delete_item(item_id)
    return {"ok": True}

@app.get("/api/orders")
def api_list_orders(authorization: str = Header(default="")):
    require_admin(authorization)
    return list_orders()

@app.patch("/api/orders/{order_id}")
def api_set_status(order_id: int, s: StatusIn, authorization: str = Header(default="")):
    require_admin(authorization)
    if s.status not in ("new", "contacted", "sold"):
        raise HTTPException(400, "status must be new|contacted|sold")
    set_order_status(order_id, s.status)
    return {"ok": True}

@app.post("/api/upload")
def upload(file: UploadFile = File(...), authorization: str = Header(default="")):
    require_admin(authorization)
    ext = os.path.splitext(file.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "Only image files allowed")
    fname = f"{int(time.time()*1000)}{ext}"
    if storage_bucket is not None:
        blob = storage_bucket.blob(f"uploads/{fname}")
        file.file.seek(0)
        blob.upload_from_file(file.file, content_type=file.content_type)
        try:
            blob.make_public()
            return {"url": blob.public_url}
        except Exception:
            url = blob.generate_signed_url(version="v4", expiration=timedelta(days=3650), method="GET")
            return {"url": url}
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file.file.seek(0)
    with open(f"{UPLOAD_DIR}/{fname}", "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/{fname}"}

# ---------------- serve frontend ----------------
os.makedirs(UPLOAD_DIR, exist_ok=True)
if os.path.exists("static"):
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
