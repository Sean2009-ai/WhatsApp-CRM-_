"""
=====================================
  WhatsApp CRM SaaS - Version 2.0
  Multi-boutiques | Dashboard | Admin
=====================================
"""

from flask import Flask, request, jsonify, render_template_string, redirect, session, send_from_directory
import os
import json
import requests
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "whatsapp-crm-secret-2024")

# =============================================
# CONFIG
# =============================================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin123")
MON_NUMERO = os.getenv("MON_NUMERO", "whatsapp:+22675000000")

# =============================================
# BASE DE DONNÉES JSON
# =============================================
DB_FILE = "crm_data.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"boutiques": {}, "commandes": [], "clients": {}}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =============================================
# IA GROQ
# =============================================
def ask_groq(messages, system_prompt):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 500,
        "messages": [{"role": "system", "content": system_prompt}] + messages
    }
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=20
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[ERREUR GROQ] {e}")
        return "Désolé, je rencontre un problème technique. Réessaie dans un instant 🙏"

# =============================================
# TWILIO
# =============================================
def envoyer_whatsapp(to, message):
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to
        )
        print(f"[WHATSAPP ENVOYÉ] {to}")
    except Exception as e:
        print(f"[ERREUR TWILIO] {e}")

# =============================================
# CINETPAY
# =============================================
def creer_lien_paiement(transaction_id, montant, nom, tel):
    try:
        payload = {
            "apikey": CINETPAY_API_KEY,
            "site_id": CINETPAY_SITE_ID,
            "transaction_id": transaction_id,
            "amount": montant,
            "currency": "XOF",
            "description": f"Commande - {nom}",
            "return_url": "https://whatsapp-crm-s4io.onrender.com/merci",
            "notify_url": "https://whatsapp-crm-s4io.onrender.com/webhook/paiement",
            "customer_name": nom,
            "customer_phone_number": tel,
            "channels": "MOBILE_MONEY",
            "lang": "fr"
        }
        resp = requests.post(
            "https://api-checkout.cinetpay.com/v2/payment",
            json=payload, timeout=20
        )
        data = resp.json()
        if data.get("code") == "201":
            return {"success": True, "lien": data["data"]["payment_url"]}
        return {"success": False, "erreur": data.get("message")}
    except Exception as e:
        return {"success": False, "erreur": str(e)}

# =============================================
# PROMPT
# =============================================
PROMPT_DEFAULT = """
Tu es Amina, assistante commerciale virtuelle au Burkina Faso.
Tu réponds en français chaleureux.
Quand prêt à payer: NOM, NUMERO, MONTANT.
Termine avec [PRET_PAIEMENT:nom|numero|montant]
"""

# =============================================
# HEALTH
# =============================================
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# =============================================
# WEBHOOK WHATSAPP
# =============================================
@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():

    from_number = request.form.get("From", "")
    message_body = request.form.get("Body", "").strip()

    print(f"[MESSAGE] {from_number}: {message_body}")

    db = load_db()

    # ===== LOCALISATION =====
    latitude = request.form.get("Latitude")
    longitude = request.form.get("Longitude")

    if latitude and longitude:

        if from_number not in db["clients"]:
            db["clients"][from_number] = {}

        db["clients"][from_number]["localisation"] = {
            "latitude": latitude,
            "longitude": longitude
        }

        save_db(db)

        resp = MessagingResponse()
        resp.message("📍 Localisation reçue avec succès ! Merci 🙌")
        return str(resp)

    # ===== CLIENT =====
    if from_number not in db["clients"]:
        db["clients"][from_number] = {
            "numero": from_number,
            "historique": [],
            "premiere_contact": datetime.now().isoformat()
        }

    client_data = db["clients"][from_number]

    client_data["historique"].append({
        "role": "user",
        "content": message_body
    })

    historique_recent = client_data["historique"][-10:]

    # ===== BOUTIQUE =====
    boutique_id = from_number.replace("whatsapp:+", "")
    boutique = db.get("boutiques", {}).get(boutique_id)

    if boutique:
        prompt = f"""
Tu es Amina pour {boutique['nom_boutique']}.
Produits: {boutique['produits']}
"""
    else:
        prompt = PROMPT_DEFAULT

    reponse_ia = ask_groq(historique_recent, prompt)
    reponse_finale = reponse_ia

    client_data["historique"].append({"role": "assistant", "content": reponse_finale})
    client_data["derniere_activite"] = datetime.now().isoformat()

    save_db(db)

    resp = MessagingResponse()
    resp.message(reponse_finale)
    return str(resp)

# =============================================
# ROOT
# =============================================
@app.route("/")
def index():
    return jsonify({"status": "WhatsApp CRM actif 🚀"})

# =============================================
# ONBOARDING
# =============================================
@app.route("/onboarding")
def onboarding():
    return send_from_directory('.', 'onboarding.html')
@app.route("/admin")
def admin_dashboard():

    db = load_db()

    boutiques = db.get("boutiques", {})
    commandes = db.get("commandes", [])

    total_payees = sum(
        1 for c in commandes
        if c.get("statut") == "ACCEPTED"
    )

    revenus_total = sum(
        c.get("montant", 0)
        for c in commandes
        if c.get("statut") == "ACCEPTED"
    )

    # Stats par boutique
    for boutique_id, b in boutiques.items():

        commandes_boutique = [
            c for c in commandes
            if c.get("boutique_id") == boutique_id
        ]

        b["nb_commandes"] = len(commandes_boutique)

        b["revenus"] = sum(
            c.get("montant", 0)
            for c in commandes_boutique
            if c.get("statut") == "ACCEPTED"
        )

    return render_template_string(
        ADMIN_HTML,
        boutiques=boutiques,
        total_boutiques=len(boutiques),
        total_commandes=len(commandes),
        total_payees=total_payees,
        revenus_total=f"{revenus_total:,} FCFA"
    )
