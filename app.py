from flask import Flask, request, render_template, jsonify
import json
import os
from datetime import datetime, timedelta
import threading

app = Flask(__name__)

DB_FILE = os.environ.get("DB_FILE", "db.json")
lock = threading.Lock()


# ================= DATABASE =================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"shops": []}

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"shops": []}


def save_db(db):
    with lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=4)


def get_shop(db, shop_id):
    return next((s for s in db["shops"] if s["id"] == shop_id), None)


# ================= STATUS =================
def get_status(shop):
    try:
        if shop.get("blocked"):
            return "BLOCKED"

        expires = shop.get("expires_at")
        if not expires:
            return "UNKNOWN"

        if datetime.now() > datetime.fromisoformat(expires):
            return "EXPIRED"

        return "ACTIVE"
    except:
        return "UNKNOWN"


# ================= ROUTES =================
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/onboarding")
def onboarding():
    return render_template("onboarding.html")


# ================= CREATE SHOP =================
@app.route("/create-shop", methods=["POST"])
def create_shop():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "no data"}), 400

        if not data.get("name") or not data.get("owner") or not data.get("phone"):
            return jsonify({"error": "missing fields"}), 400

        db = load_db()

        shop_id = os.urandom(4).hex().upper()

        shop = {
            "id": shop_id,
            "name": data["name"],
            "owner": data["owner"],
            "phone": data["phone"],
            "blocked": False,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=30)).isoformat(),
            "orders": 0,
            "revenue": 0
        }

        db["shops"].append(shop)
        save_db(db)

        return jsonify({
            "shop_id": shop_id,
            "dashboard": f"/dashboard/{shop_id}"
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": "server error"}), 500


# ================= DASHBOARD =================
@app.route("/dashboard/<shop_id>")
def dashboard(shop_id):
    db = load_db()
    shop = get_shop(db, shop_id)

    if not shop:
        return "Boutique introuvable"

    shop["status"] = get_status(shop)
    return render_template("dashboard.html", shop=shop)


# ================= ADMIN =================
@app.route("/admin")
def admin():
    if request.args.get("key") != "1234":
        return "Unauthorized", 403

    db = load_db()
    shops = db.get("shops", [])

    for s in shops:
        s["status"] = get_status(s)

    return render_template("admin.html", shops=shops)


@app.route("/admin/toggle/<shop_id>")
def toggle(shop_id):
    if request.args.get("key") != "1234":
        return "Unauthorized", 403

    db = load_db()
    shop = get_shop(db, shop_id)

    if shop:
        shop["blocked"] = not shop.get("blocked", False)
        save_db(db)

    return jsonify({"success": True})


# ================= STATS API =================
@app.route("/api/stats/<shop_id>")
def stats(shop_id):
    db = load_db()
    shop = get_shop(db, shop_id)

    if not shop:
        return jsonify({"error": "not found"})

    return jsonify({
        "orders": shop.get("orders", 0),
        "revenue": shop.get("revenue", 0),
        "status": get_status(shop),
        "blocked": shop.get("blocked", False),
        "expires_at": shop.get("expires_at")
    })


# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
