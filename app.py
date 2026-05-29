"""
=====================================
  WhatsApp CRM Lite - MVP Complet
  Version corrigée et fonctionnelle
=====================================
"""

import os
import json
import requests

from flask import Flask, request, jsonify, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from datetime import datetime

# =============================================
# CONFIG FLASK
# =============================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key")

# =============================================
# CONFIGURATION APIs
# =============================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# Sandbox Twilio WhatsApp
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

# =============================================
# BASE DE DONNÉES JSON
# =============================================

DB_FILE = "crm_data.json"


def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "clients": {},
        "commandes": [],
        "boutiques": {}
    }


def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =============================================
# PROMPT PAR DÉFAUT
# =============================================

SYSTEM_PROMPT = """
Tu es Amina, une assistante commerciale virtuelle d'une boutique en ligne au Burkina Faso.

Tu réponds uniquement en français simple et chaleureux.

Ton rôle:
1. Accueillir le client
2. Comprendre son besoin
3. Proposer les produits
4. Répondre aux objections
5. Demander les infos de paiement quand le client veut acheter

Produits:
- Téléphones
- Accessoires
- Livraison Ouaga

Quand le client est prêt à payer:
demande:
- nom
- numéro mobile money
- montant

Quand tu as toutes les infos termine EXACTEMENT par:

[PRET_PAIEMENT:nom|numero|montant]
"""


# =============================================
# IA GROQ
# =============================================

def ask_groq(conversation_history, system_prompt):

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ] + conversation_history

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 400
    }

    try:

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=20
        )

        resp.raise_for_status()

        data = resp.json()

        print("[GROQ OK]")
        print(data)

        return data["choices"][0]["message"]["content"]

    except Exception as e:

        print(f"[ERREUR GROQ] {e}")

        return (
            "Désolé 🙏 "
            "Je rencontre un petit problème technique. "
            "Réessaie dans quelques instants."
        )


# =============================================
# CINETPAY
# =============================================

def creer_lien_paiement(transaction_id, montant, nom_client, tel_client):

    payload = {
        "apikey": CINETPAY_API_KEY,
        "site_id": CINETPAY_SITE_ID,
        "transaction_id": transaction_id,
        "amount": montant,
        "currency": "XOF",
        "description": f"Commande WhatsApp - {nom_client}",
        "return_url": "https://ton-site.com/merci",
        "notify_url": "https://ton-site.com/webhook/paiement",
        "customer_name": nom_client,
        "customer_phone_number": tel_client,
        "channels": "MOBILE_MONEY",
        "lang": "fr"
    }

    try:

        resp = requests.post(
            "https://api-checkout.cinetpay.com/v2/payment",
            json=payload,
            timeout=20
        )

        data = resp.json()

        print(data)

        if data.get("code") == "201":

            return {
                "success": True,
                "lien": data["data"]["payment_url"]
            }

        return {
            "success": False,
            "erreur": data.get("message")
        }

    except Exception as e:

        return {
            "success": False,
            "erreur": str(e)
        }


def verifier_paiement(transaction_id):

    payload = {
        "apikey": CINETPAY_API_KEY,
        "site_id": CINETPAY_SITE_ID,
        "transaction_id": transaction_id
    }

    try:

        resp = requests.post(
            "https://api-checkout.cinetpay.com/v2/payment/check",
            json=payload,
            timeout=20
        )

        data = resp.json()

        return {
            "statut": data.get("data", {}).get("status", "UNKNOWN"),
            "raw": data
        }

    except Exception as e:

        return {
            "statut": "ERREUR",
            "erreur": str(e)
        }


# =============================================
# ENVOI WHATSAPP
# =============================================

def envoyer_message_whatsapp(to_number, message):

    try:

        client = Client(
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN
        )

        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to_number
        )

        print(f"[MESSAGE ENVOYÉ] {to_number}")

    except Exception as e:

        print(f"[ERREUR TWILIO] {e}")


# =============================================
# HEALTH CHECK
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

    print(f"[MESSAGE] {from_number} -> {message_body}")

    db = load_db()

    # Création client
    if from_number not in db["clients"]:

        db["clients"][from_number] = {
            "numero": from_number,
            "historique": [],
            "statut": "nouveau",
            "premiere_contact": datetime.now().isoformat()
        }

    client_data = db["clients"][from_number]

    # Historique utilisateur
    client_data["historique"].append({
        "role": "user",
        "content": message_body
    })

    historique_recent = client_data["historique"][-10:]

    # =============================================
    # PROMPT DYNAMIQUE BOUTIQUE
    # =============================================

    boutique_id = from_number.replace("whatsapp:+", "")

    boutique = db.get("boutiques", {}).get(boutique_id)

    if boutique:

        prompt = f"""
Tu es Amina, assistante commerciale de {boutique['nom']}.

Ville:
{boutique['ville']}

Produits:
{boutique['produits']}

Message spécial:
{boutique.get('message_perso', '')}

Tu réponds en français chaleureux style Afrique de l'Ouest.

Quand le client veut payer:
demande:
- nom
- numéro mobile money
- montant

Termine avec:
[PRET_PAIEMENT:nom|numero|montant]
"""

    else:

        prompt = SYSTEM_PROMPT

    # =============================================
    # IA
    # =============================================

    reponse_ia = ask_groq(
        historique_recent,
        prompt
    )

    reponse_finale = reponse_ia

    # =============================================
    # DÉTECTION PAIEMENT
    # =============================================

    if "[PRET_PAIEMENT:" in reponse_ia:

        try:

            debut = reponse_ia.index("[PRET_PAIEMENT:") + len("[PRET_PAIEMENT:")
            fin = reponse_ia.index("]", debut)

            infos = reponse_ia[debut:fin].split("|")

            nom = infos[0]
            numero = infos[1]

            montant = int(
                infos[2]
                .replace("FCFA", "")
                .replace("fcfa", "")
                .replace(" ", "")
            )

            transaction_id = (
                f"CMD_{int(datetime.now().timestamp())}"
            )

            paiement = creer_lien_paiement(
                transaction_id,
                montant,
                nom,
                numero
            )

            db["commandes"].append({
                "transaction_id": transaction_id,
                "client": from_number,
                "nom": nom,
                "numero_mobile_money": numero,
                "montant": montant,
                "statut": "EN_ATTENTE",
                "date": datetime.now().isoformat()
            })

            texte_clean = reponse_ia.split("[PRET_PAIEMENT:")[0].strip()

            if paiement["success"]:

                reponse_finale = f"""
{texte_clean}

✅ Commande créée !

👤 {nom}
💰 {montant:,} FCFA

🔗 Clique ici pour payer:
{paiement['lien']}

Merci pour ta confiance 🙏
"""

            else:

                reponse_finale = (
                    "⚠️ Impossible de générer "
                    "le lien de paiement."
                )

        except Exception as e:

            print(f"[ERREUR PAIEMENT] {e}")

    # Historique assistant
    client_data["historique"].append({
        "role": "assistant",
        "content": reponse_finale
    })

    client_data["derniere_activite"] = datetime.now().isoformat()

    save_db(db)

    resp = MessagingResponse()
    resp.message(reponse_finale)

    return str(resp)


# =============================================
# WEBHOOK PAIEMENT
# =============================================

@app.route("/webhook/paiement", methods=["POST"])
def webhook_paiement():

    data = request.json or request.form.to_dict()

    transaction_id = (
        data.get("cpm_trans_id")
        or data.get("transaction_id")
    )

    if not transaction_id:

        return jsonify({
            "status": "error"
        }), 400

    verification = verifier_paiement(transaction_id)

    db = load_db()

    for commande in db["commandes"]:

        if commande["transaction_id"] == transaction_id:

            commande["statut"] = verification["statut"]

            if verification["statut"] == "ACCEPTED":

                envoyer_message_whatsapp(
                    commande["client"],
                    (
                        f"🎉 Paiement confirmé !\n\n"
                        f"Merci {commande['nom']} 🙏\n"
                        f"Montant reçu: "
                        f"{commande['montant']:,} FCFA"
                    )
                )

            break

    save_db(db)

    return jsonify({"status": "ok"})


# =============================================
# DASHBOARD
# =============================================

@app.route("/dashboard")
def dashboard():

    db = load_db()

    commandes = db.get("commandes", [])

    total_clients = len(db.get("clients", {}))

    paiements_ok = sum(
        1 for c in commandes
        if c["statut"] == "ACCEPTED"
    )

    revenus = sum(
        c["montant"]
        for c in commandes
        if c["statut"] == "ACCEPTED"
    )

    return jsonify({
        "clients": total_clients,
        "paiements_ok": paiements_ok,
        "revenus": revenus,
        "commandes": commandes[-10:]
    })


# =============================================
# MAIN
# =============================================

if __name__ == "__main__":

    port = int(os.getenv("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
