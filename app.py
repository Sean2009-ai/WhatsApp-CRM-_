from flask import Flask, request, render_template, jsonify, redirect
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
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP")   # Ton numéro personnel

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
        client.messages.create(
            from_='whatsapp:+14155238886',
            body=body,
            to=f'whatsapp:{to}'
        )
        return True
    except:
        return False

# ================= PROMPT AMINA =================
SYSTEM_PROMPT = """Tu es Amina, une assistante commerciale burkinabè chaleureuse, professionnelle et persuasive."""

def ask_amina(message):
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message}]
        completion = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=messages,
            temperature=0.75,
            max_tokens=900
        )
        return completion.choices[0].message.content.strip()
    except:
        return "Désolée, je n'ai pas compris. Peux-tu répéter ?"

# ================= ROUTES =================
@app.route("/")
def home():
    return "<h1>WhatsApp CRM SaaS</h1><br><a href='/onboarding'>Créer ma Boutique (35 000 FCFA)</a> | <a href='/admin/dashboard'>Admin Dashboard</a>"

@app.route("/onboarding")
def onboarding():
    return render_template("onboarding.html")

@app.route("/submit-onboarding", methods=["POST"])
def submit_onboarding():
    data = request.json
    boutique_id = str(uuid.uuid4())[:8].upper()
    
    db = load_db()
    db["boutiques"].append({
        "boutique_id": boutique_id,
        "nom_boutique": data.get("nom_boutique"),
        "ville": data.get("ville"),
        "whatsapp": data.get("whatsapp"),
        "orange_money": data.get("orange_money"),
        "email": data.get("email"),
        "tarif": "Unique - 35 000 FCFA",
        "message_perso": data.get("message_perso"),
        "statut": "ACTIVE",
        "blocked": False,
        "date_creation": datetime.now().isoformat(),
        "date_expiration": (datetime.now() + timedelta(days=30)).isoformat(),
        "prix_abonnement": 35000
    })
    save_db(db)

    return jsonify({
        "success": True,
        "boutique_id": boutique_id,
        "dashboard_url": f"https://whatsapp-crm-s4io.onrender.com/dashboard/{boutique_id}"
    })

# ================= ADMIN DASHBOARD =================
@app.route("/admin/dashboard")
def admin_dashboard():
    db = load_db()
    boutiques = db.get("boutiques", [])
    now = datetime.now()

    expired = [b for b in boutiques if datetime.fromisoformat(b.get("date_expiration", "")) < now]

    # Alertes
    for b in expired:
        envoyer_message_whatsapp(ADMIN_WHATSAPP.replace("+226",""), f"⚠️ ALERTE ABONNEMENT\n{b['nom_boutique']} ({b['boutique_id']}) a expiré !")
        if b.get("whatsapp"):
            envoyer_message_whatsapp(b["whatsapp"].replace("+226",""), f"⚠️ Votre abonnement Amina (35 000 FCFA) a expiré.\nVeuillez renouveler.")

    html = f"""
    <h1>📊 Admin Dashboard</h1>
    <h2>Abonnements Expirés : {len(expired)}</h2>
    <table border="1" cellpadding="10" style="width:100%;border-collapse:collapse;">
        <tr><th>ID</th><th>Boutique</th><th>Tarif</th><th>Expiration</th><th>Statut</th><th>Action</th></tr>
    """
    for b in boutiques:
        exp = b.get("date_expiration", "")[:10]
        days = (datetime.fromisoformat(b["date_expiration"]) - now).days if "date_expiration" in b else "N/A"
        color = "red" if b.get("blocked") or days < 0 else "green"
        action = f'<a href="/admin/block/{b["boutique_id"]}">Bloquer/Débloquer</a>'
        html += f"<tr><td>{b['boutique_id']}</td><td>{b['nom_boutique']}</td><td>35 000 FCFA</td><td>{exp}</td><td style='color:{color}'>{b.get('statut')}</td><td>{action}</td></tr>"
    html += "</table>"
    return html

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

# ================= WEBHOOK =================
@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    from_number = request.values.get('From', '').replace('whatsapp:', '')

    reponse = ask_amina(incoming_msg)

    if "[PRET_PAIEMENT:" in reponse:
        try:
            data_str = reponse.split("[PRET_PAIEMENT:")[1].split("]")[0]
            nom, produit, quantite, adresse, montant = [x.strip() for x in data_str.split("|")]
            db = load_db()
            db["commandes"].append({
                "client": from_number,
                "nom_client": nom,
                "produit": produit,
                "quantite": quantite,
                "adresse": adresse,
                "montant": montant,
                "statut": "EN_ATTENTE",
                "date": datetime.now().isoformat()
            })
            save_db(db)
        except:
            pass

    envoyer_message_whatsapp(from_number, reponse)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
