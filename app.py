from flask import Flask, request, render_template_string, jsonify
import os
import json
from datetime import datetime
from twilio.rest import Client
from groq import Groq
import requests

app = Flask(__name__)

# ================= CONFIG =================
TWILIO_MAIN_SID = os.getenv("TWILIO_MAIN_ACCOUNT_SID")
TWILIO_MAIN_TOKEN = os.getenv("TWILIO_MAIN_AUTH_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

groq_client = Groq(api_key=GROQ_API_KEY)

# Base de données simple (JSON) - À remplacer par PostgreSQL plus tard
DB_FILE = "crm_data.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"commandes": [], "boutiques": []}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

# ================= FONCTIONS TWILIO =================
def creer_subaccount_twilio(nom_boutique: str):
    client = Client(TWILIO_MAIN_SID, TWILIO_MAIN_TOKEN)
    subaccount = client.api.accounts.create(
        friendly_name=f"Amina - {nom_boutique} - {datetime.now().strftime('%Y-%m-%d')}"
    )
    return {
        "subaccount_sid": subaccount.sid,
        "subaccount_auth_token": subaccount.auth_token,
        "friendly_name": subaccount.friendly_name
    }

def envoyer_message_whatsapp(to: str, body: str, subaccount_sid=None, subaccount_token=None):
    if subaccount_sid and subaccount_token:
        client = Client(subaccount_sid, subaccount_token)
    else:
        client = Client(TWILIO_MAIN_SID, TWILIO_MAIN_TOKEN)
    
    message = client.messages.create(
        from_='whatsapp:+14155238886',  # Sandbox Twilio
        body=body,
        to=f'whatsapp:{to}'
    )
    return message.sid

# ================= PROMPT AMINA =================
SYSTEM_PROMPT = """Tu es Amina, une assistante commerciale dynamique, professionnelle et persuasive.
Tu parles en français simple et chaleureux (style burkinabè).
Tu aides à vendre les produits de la boutique.
Quand le client dit qu'il est prêt à payer, tu réponds avec le tag exact : [PRET_PAIEMENT:nom|numero|montant]"""

def ask_amina(message: str, historique=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if historique:
        messages.extend(historique)
    messages.append({"role": "user", "content": message})
    
    completion = groq_client.chat.completions.create(
        model="llama3-70b-8192",
        messages=messages,
        temperature=0.7,
        max_tokens=800
    )
    return completion.choices[0].message.content

# ================= ROUTES =================
@app.route("/")
def home():
    return "✅ WhatsApp CRM SaaS - Amina est en ligne"

@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    from_number = request.values.get('From', '').replace('whatsapp:', '')
    
    db = load_db()
    
    # Recherche de la boutique/client
    reponse = ask_amina(incoming_msg)
    
    # Détection paiement
    if "[PRET_PAIEMENT:" in reponse:
        try:
            data = reponse.split("[PRET_PAIEMENT:")[1].split("]")[0]
            nom, numero, montant = data.split("|")
            montant = int(montant)
            
            transaction_id = f"CMD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            db["commandes"].append({
                "transaction_id": transaction_id,
                "client": from_number,
                "nom": nom,
                "montant": montant,
                "statut": "EN_ATTENTE",
                "date": datetime.now().isoformat()
            })
            save_db(db)
            
            # Lien CinetPay
            lien_paiement = f"https://pay.cinetpay.com/?apikey={CINETPAY_API_KEY}&site_id={CINETPAY_SITE_ID}&amount={montant}&currency=XOF&transaction_id={transaction_id}"
            
            reponse = f"Parfait {nom} !\nPour confirmer ta commande de {montant} FCFA, clique ici :\n{lien_paiement}\n\nDès que tu paies, Amina sera activée pour ta boutique."
        
        except:
            reponse = "Désolée, il y a eu une erreur avec le paiement."
    
    envoyer_message_whatsapp(from_number, reponse)
    return "OK", 200

@app.route("/webhook/paiement", methods=["POST"])
def webhook_paiement():
    data = request.json or request.form.to_dict()
    transaction_id = data.get("cpm_trans_id") or data.get("transaction_id")
    
    if not transaction_id:
        return jsonify({"status": "error"}), 400
    
    db = load_db()
    
    for commande in db["commandes"]:
        if commande["transaction_id"] == transaction_id and commande["statut"] == "EN_ATTENTE":
            
            # === AUTOMATISATION TWILIO ===
            nom_boutique = commande.get("nom", "Client")
            result = creer_subaccount_twilio(nom_boutique)
            
            commande["twilio_subaccount_sid"] = result["subaccount_sid"]
            commande["twilio_auth_token"] = result["subaccount_auth_token"]
            commande["statut"] = "ACTIVE"
            commande["date_activation"] = datetime.now().isoformat()
            
            save_db(db)
            
            message_success = f"""
✅ *Félicitations {nom_boutique} !*

Votre Amina est maintenant activée pour votre boutique.

🔑 Subaccount SID : {result['subaccount_sid']}
🔑 Token : {result['subaccount_auth_token'][:10]}... (sécurisé)

Vous pouvez maintenant utiliser ce numéro pour vos clients.
Amina va répondre automatiquement 24h/24.
            """
            
            envoyer_message_whatsapp(commande["client"], message_success)
            break
    
    return jsonify({"status": "success"}), 200

@app.route("/dashboard")
def dashboard():
    db = load_db()
    html = """
    <h1>Dashboard Amina SaaS</h1>
    <h2>Commandes Actives</h2>
    <pre>{{ commandes }}</pre>
    """
    return render_template_string(html, commandes=json.dumps(db["commandes"], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
