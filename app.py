from flask import Flask, request, render_template_string, jsonify, redirect
import os
import json
from datetime import datetime, timedelta
from twilio.rest import Client
from groq import Groq
import uuid

app = Flask(__name__)

# ================= CONFIG =================
TWILIO_MAIN_SID = os.getenv("TWILIO_MAIN_ACCOUNT_SID")
TWILIO_MAIN_TOKEN = os.getenv("TWILIO_MAIN_AUTH_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)
DB_FILE = "crm_data.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"boutiques": [], "commandes": []}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

def envoyer_message_whatsapp(to, body):
    try:
        client = Client(TWILIO_MAIN_SID, TWILIO_MAIN_TOKEN)
        client.messages.create(from_='whatsapp:+14155238886', body=body, to=f'whatsapp:{to}')
        return True
    except:
        return False

# ================= TON ONBOARDING HTML ORIGINAL (Intégré) =================
# Colle ici TON code HTML complet que tu m'as envoyé précédemment
# (Je le mets en résumé, mais tu dois mettre la version complète)

ONBOARDING_HTML = """[COLLE ICI TON CODE HTML COMPLET QUE TU M'AS ENVOYÉ]"""

# ================= ROUTE SUBMIT (Adaptée à ton formulaire) =================
@app.route("/submit-onboarding", methods=["POST"])
def submit_onboarding():
    data = request.json
    
    boutique_id = str(uuid.uuid4())[:8].upper()
    expiration = (datetime.now() + timedelta(days=30)).isoformat()

    db = load_db()
    boutique = {
        "boutique_id": boutique_id,
        "nom_boutique": data.get("nom_boutique"),
        "ville": data.get("ville"),
        "description": data.get("description"),
        "whatsapp": data.get("whatsapp"),
        "orange_money": data.get("orange_money"),
        "email": data.get("email"),
        "produits": data.get("produits"),
        "tarif": data.get("tarif"),
        "message_perso": data.get("message_perso"),
        "statut": "ACTIVE",
        "blocked": False,
        "date_creation": datetime.now().isoformat(),
        "date_expiration": expiration
    }
    
    db["boutiques"].append(boutique)
    save_db(db)

    return jsonify({
        "success": True,
        "boutique_id": boutique_id,
        "dashboard_url": f"http://127.0.0.1:5000/dashboard/{boutique_id}"
    })

# ================= ADMIN DASHBOARD (avec stats + blocage + alertes) =================
@app.route("/admin/dashboard")
def admin_dashboard():
    db = load_db()
    boutiques = db.get("boutiques", [])
    now = datetime.now()

    expired = [b for b in boutiques if "date_expiration" in b and datetime.fromisoformat(b["date_expiration"]) < now]

    html = f"""
    <h1>📊 Admin Dashboard</h1>
    <h2>⚠️ Abonnements Expirés : {len(expired)}</h2>
    <table border="1" cellpadding="10" style="width:100%; border-collapse:collapse;">
        <tr><th>ID</th><th>Boutique</th><th>Tarif</th><th>Expiration</th><th>Statut</th><th>Action</th></tr>
    """
    for b in boutiques:
        exp = b.get("date_expiration", "")[:10]
        status = b.get("statut", "ACTIVE")
        action = f'<a href="/admin/block/{b["boutique_id"]}">Bloquer/Débloquer</a>'
        html += f"<tr><td>{b['boutique_id']}</td><td>{b['nom_boutique']}</td><td>{b.get('tarif')}</td><td>{exp}</td><td>{status}</td><td>{action}</td></tr>"
    html += "</table>"
    return render_template_string(html)

@app.route("/admin/block/<boutique_id>")
def block_boutique(boutique_id):
    db = load_db()
    for b in db["boutiques"]:
        if b["boutique_id"] == boutique_id:
            b["blocked"] = not b.get("blocked", False)
            b["statut"] = "BLOQUÉ" if b["blocked"] else "ACTIVE"
            save_db(db)
            break
    return redirect("/admin/dashboard")

@app.route("/onboarding")
def onboarding():
    return render_template_string(ONBOARDING_HTML)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
