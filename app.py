from flask import Flask, request, render_template, jsonify
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)

DB_FILE = "db.json"


# ================= DB =================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"shops": []}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4)


def get_shop(db, shop_id):
    for s in db["shops"]:
        if s["id"] == shop_id:
            return s
    return None


# ================= STATUS ENGINE =================
def check_status(shop):
    try:
        if shop.get("blocked"):
            return "BLOCKED"

        expires = datetime.fromisoformat(shop["expires_at"])
        if datetime.now() > expires:
            return "EXPIRED"

        return "ACTIVE"
    except:
        return "UNKNOWN"


# ================= HOME =================
@app.route("/")
def home():
    return """
    <h1>WhatsApp SaaS V2.1</h1>
    <a href='/onboarding'>Créer boutique</a><br>
    <a href='/admin'>Admin</a>
    """


# ================= ONBOARDING =================
@app.route("/onboarding")
def onboarding():
    return render_template("onboarding.html")


@@app.route("/create-shop", methods=["POST"])
def create_shop():
    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({"error": "no data received"}), 400

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
        print("ERROR CREATE SHOP:", e)
        return jsonify({"error": "server error"}), 500

# ================= DASHBOARD CLIENT =================
@app.route("/dashboard/<shop_id>")
def dashboard(shop_id):
    db = load_db()
    shop = get_shop(db, shop_id)

    if not shop:
        return "Boutique introuvable"

    shop["status"] = check_status(shop)

    return render_template("dashboard.html", shop=shop)


# ================= ADMIN =================
@app.route("/admin")
def admin():
    db = load_db()

    for shop in db["shops"]:
        shop["status"] = check_status(shop)

    return render_template("admin.html", shops=db["shops"])


@app.route("/admin/toggle/<shop_id>")
def toggle(shop_id):
    db = load_db()
    shop = get_shop(db, shop_id)

    if shop:
        shop["blocked"] = not shop.get("blocked", False)
        save_db(db)

    return jsonify({"success": True})


# ================= API STATS =================
@app.route("/api/stats/<shop_id>")
def stats(shop_id):
    db = load_db()
    shop = get_shop(db, shop_id)

    if not shop:
        return jsonify({"error": "not found"})

    shop["status"] = check_status(shop)

    return jsonify({
        "orders": shop.get("orders", 0),
        "revenue": shop.get("revenue", 0),
        "status": shop["status"],
        "blocked": shop.get("blocked", False),
        "expires_at": shop.get("expires_at")
    })


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
