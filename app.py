from flask import Flask, request, jsonify, render_template
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
import json
import os
import re
import uuid
from html import escape

app = Flask(__name__)

# =========================
# CONFIG
# =========================

DATA_DIR = "data"
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
STORES_FILE = os.path.join(DATA_DIR, "stores.json")

os.makedirs(DATA_DIR, exist_ok=True)

# =========================
# HELPERS
# =========================

def load_json(path, default=[]):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f)

    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def sanitize_text(text):
    return escape(str(text).strip())


def normalize_phone(phone):
    """
    Convertit:
    +22670112233
    70 11 22 33
    0022670112233
    vers:
    22670112233
    """

    phone = re.sub(r"\D", "", phone)

    if phone.startswith("00"):
        phone = phone[2:]

    if phone.startswith("226") and len(phone) == 11:
        return phone

    if len(phone) == 8:
        return "226" + phone

    return None


def valid_phone(phone):
    return bool(re.fullmatch(r"226\d{8}", phone))


# =========================
# DATABASE
# =========================

orders = load_json(ORDERS_FILE, [])
stores = load_json(STORES_FILE, [])

# =========================
# STORE CREATION
# =========================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create-store", methods=["POST"])
def create_store():

    data = request.form

    store_name = sanitize_text(data.get("store_name"))
    owner_name = sanitize_text(data.get("owner_name"))
    whatsapp_number = normalize_phone(data.get("whatsapp_number"))
    orange_money = normalize_phone(data.get("orange_money"))
    plan = sanitize_text(data.get("plan"))

    if not store_name:
        return jsonify({"error": "Nom boutique requis"}), 400

    if not owner_name:
        return jsonify({"error": "Nom propriétaire requis"}), 400

    if not valid_phone(whatsapp_number):
        return jsonify({
            "error": "Numéro WhatsApp invalide. Format: 226XXXXXXXX"
        }), 400

    if not valid_phone(orange_money):
        return jsonify({
            "error": "Numéro Orange Money invalide."
        }), 400

    # PAYWALL OBLIGATOIRE
    payment_status = data.get("payment_status")

    if payment_status != "paid":
        return jsonify({
            "error": "Paiement obligatoire avant création du bot."
        }), 403

    # PRODUITS
    products = []

    product_names = request.form.getlist("product_name[]")
    product_prices = request.form.getlist("product_price[]")
    product_images = request.form.getlist("product_image[]")

    for i in range(len(product_names)):

        name = sanitize_text(product_names[i])
        price = sanitize_text(product_prices[i])

        image = ""
        if i < len(product_images):
            image = sanitize_text(product_images[i])

        if name and price:
            products.append({
                "name": name,
                "price": price,
                "image": image
            })

    store_id = str(uuid.uuid4())

    store = {
        "id": store_id,
        "store_name": store_name,
        "owner_name": owner_name,
        "whatsapp_number": whatsapp_number,
        "orange_money": orange_money,
        "plan": plan,
        "products": products,
        "created_at": datetime.now().isoformat()
    }

    stores.append(store)
    save_json(STORES_FILE, stores)

    # SANDBOX PARTAGÉ
    # IMPORTANT :
    # Chaque boutique est liée à SON numéro WhatsApp.
    # Cela évite le mélange des messages entre boutiques.

    sandbox_code = "join boutique-" + store_id[:6]

    return jsonify({
        "success": True,
        "store_id": store_id,
        "sandbox_code": sandbox_code,
        "message": "Boutique créée avec succès"
    })


# =========================
# FIND STORE
# =========================

def find_store_by_whatsapp(phone):

    normalized = normalize_phone(phone)

    for store in stores:
        if store["whatsapp_number"] == normalized:
            return store

    return None


# =========================
# TWILIO WEBHOOK
# =========================

@app.route("/webhook", methods=["POST"])
def webhook():

    incoming_msg = request.values.get("Body", "").strip()

    sender = request.values.get("From", "")

    sender = re.sub(r"whatsapp:\+", "", sender)

    sender = normalize_phone(sender)

    response = MessagingResponse()
    msg = response.message()

    # =====================
    # PROTECTION SANDBOX
    # =====================

    store = find_store_by_whatsapp(sender)

    if not store:
        msg.body(
            "❌ Aucun assistant lié à ce numéro.\n"
            "Veuillez contacter la boutique."
        )
        return str(response)

    products = store["products"]

    # =====================
    # LISTE PRODUITS
    # =====================

    if incoming_msg.lower() in ["salut", "bonjour", "hello", "menu"]:

        text = f"👋 Bienvenue chez {store['store_name']}\n\n"

        text += "🛍 Nos produits :\n\n"

        for i, p in enumerate(products):
            text += (
                f"{i+1}. {p['name']} - {p['price']} FCFA\n"
            )

        text += (
            "\nRépondez avec le numéro du produit."
        )

        msg.body(text)

        return str(response)

    # =====================
    # CHOIX PRODUIT
    # =====================

    if incoming_msg.isdigit():

        index = int(incoming_msg) - 1

        if index >= 0 and index < len(products):

            product = products[index]

            order = {
                "id": str(uuid.uuid4()),
                "store_id": store["id"],
                "store_name": store["store_name"],
                "customer_phone": sender,
                "product_name": product["name"],
                "amount": product["price"],
                "status": "en attente",
                "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "step": "address"
            }

            orders.append(order)
            save_json(ORDERS_FILE, orders)

            # IMAGE PRODUIT
            if product["image"]:
                msg.media(product["image"])

            msg.body(
                f"🛒 Produit sélectionné : {product['name']}\n\n"
                "📍 Envoyez maintenant votre adresse de livraison."
            )

            return str(response)

    # =====================
    # ETAPE ADRESSE
    # =====================

    for order in orders:

        if (
            order["customer_phone"] == sender
            and order.get("step") == "address"
        ):

            order["address"] = sanitize_text(incoming_msg)
            order["step"] = "name"

            save_json(ORDERS_FILE, orders)

            msg.body(
                "👤 Envoyez votre nom complet."
            )

            return str(response)

    # =====================
    # ETAPE NOM CLIENT
    # =====================

    for order in orders:

        if (
            order["customer_phone"] == sender
            and order.get("step") == "name"
        ):

            order["customer_name"] = sanitize_text(incoming_msg)
            order["step"] = "confirm"

            save_json(ORDERS_FILE, orders)

            msg.body(
                "✅ Commande enregistrée.\n\n"
                "Amina va confirmer votre commande bientôt."
            )

            return str(response)

    # =====================
    # DEFAULT
    # =====================

    msg.body(
        "🤖 Tapez 'menu' pour voir les produits."
    )

    return str(response)


# =========================
# DASHBOARD ADMIN
# =========================

@app.route("/admin")
def admin():

    return jsonify({
        "total_orders": len(orders),
        "orders": orders
    })


# =========================
# UPDATE STATUS
# =========================

@app.route("/update-order/<order_id>", methods=["POST"])
def update_order(order_id):

    data = request.json

    new_status = sanitize_text(data.get("status"))

    for order in orders:

        if order["id"] == order_id:

            order["status"] = new_status

            save_json(ORDERS_FILE, orders)

            return jsonify({
                "success": True
            })

    return jsonify({
        "error": "Commande introuvable"
    }), 404


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(debug=True)
