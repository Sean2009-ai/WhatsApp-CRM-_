cat > /mnt/user-data/outputs/whatsapp_crm_v2/app.py << 'ENDOFFILE'
"""
=====================================
  WhatsApp CRM SaaS - Version 3.0
  Multi-boutiques | Admin | Abonnement
  Blocage | Notifications | Production
=====================================
"""

import os
import json
import re
import requests
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "whatsapp-crm-secret-2024")

# =============================================
# CONFIG
# =============================================
TWILIO_ACCOUNT_SID     = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN      = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"

GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin123")
MON_NUMERO  = os.getenv("MON_NUMERO", "whatsapp:+22675000000")
APP_URL     = os.getenv("APP_URL", "https://whatsapp-crm-s4io.onrender.com")

PRIX_ABONNEMENT = 35000
DUREE_ABONNEMENT_JOURS = 30

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
# SÉCURITÉ
# =============================================
def sanitize(text):
    if not text:
        return ""
    text = str(text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace('"', "&quot;").replace("'", "&#x27;")
    return text.strip()

def valider_numero(numero):
    numero_propre = re.sub(r'\s+', '', str(numero))
    return bool(re.match(r'^\+226[0-9]{8}$', numero_propre))

def valider_email(email):
    return bool(re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', str(email)))

# =============================================
# ABONNEMENT
# =============================================
def boutique_active(boutique):
    if boutique.get("statut") == "bloque":
        return False, "bloque"
    expiration_str = boutique.get("date_expiration")
    if not expiration_str:
        return False, "expire"
    expiration = datetime.fromisoformat(expiration_str)
    if datetime.now() > expiration:
        return False, "expire"
    return True, "actif"

def jours_restants(boutique):
    expiration_str = boutique.get("date_expiration")
    if not expiration_str:
        return 0
    expiration = datetime.fromisoformat(expiration_str)
    delta = expiration - datetime.now()
    return max(0, delta.days)

def verifier_expirations():
    db = load_db()
    for bid, boutique in db["boutiques"].items():
        jours = jours_restants(boutique)
        whatsapp = boutique.get("whatsapp", "")

        # Rappel 3 jours avant
        if jours == 3:
            envoyer_whatsapp(
                f"whatsapp:{whatsapp}",
                f"⚠️ *Rappel abonnement*\n\n"
                f"Bonjour {boutique['nom_boutique']} !\n"
                f"Votre abonnement Amina expire dans *3 jours*.\n"
                f"Renouvelez maintenant pour continuer à recevoir des commandes.\n\n"
                f"💰 Renouvellement: *{PRIX_ABONNEMENT:,} FCFA*\n"
                f"📱 Contactez-nous pour renouveler."
            )
            envoyer_whatsapp(
                MON_NUMERO,
                f"⚠️ Boutique {boutique['nom_boutique']} expire dans 3 jours !"
            )

        # Expiration
        if jours == 0 and boutique.get("statut") == "actif":
            db["boutiques"][bid]["statut"] = "expire"
            envoyer_whatsapp(
                f"whatsapp:{whatsapp}",
                f"🔴 *Abonnement expiré*\n\n"
                f"Bonjour {boutique['nom_boutique']} !\n"
                f"Votre abonnement Amina a expiré.\n"
                f"Amina ne répond plus à vos clients.\n\n"
                f"Renouvelez maintenant: *{PRIX_ABONNEMENT:,} FCFA*"
            )
            envoyer_whatsapp(
                MON_NUMERO,
                f"🔴 Boutique {boutique['nom_boutique']} - abonnement EXPIRÉ !"
            )

    save_db(db)

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
            "return_url": f"{APP_URL}/merci",
            "notify_url": f"{APP_URL}/webhook/paiement",
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
# PROMPT PAR DÉFAUT
# =============================================
PROMPT_DEFAULT = """
Tu es Amina, une assistante commerciale virtuelle au Burkina Faso.
Tu réponds en français chaleureux style Afrique de l'Ouest.
Tu accueilles le client, identifies son besoin, présentes les produits et gères les objections.
Quand le client veut commander, collecte obligatoirement:
- Son NOM COMPLET
- Le PRODUIT commandé
- Sa VILLE / ADRESSE de livraison
- Son NUMÉRO MOBILE MONEY
- Le MONTANT total

Quand tu as TOUTES ces infos, termine avec:
[PRET_PAIEMENT:nom|produit|adresse|numero|montant]
"""

# =============================================
# HEALTH CHECK
# =============================================
@app.route("/health")
def health():
    verifier_expirations()
    return jsonify({"status": "ok"})

# =============================================
# WEBHOOK WHATSAPP
# =============================================
@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    from_number = request.form.get("From", "")
    message_body = sanitize(request.form.get("Body", "").strip())
    print(f"[MESSAGE] {from_number}: {message_body}")

    db = load_db()

    if from_number not in db["clients"]:
        db["clients"][from_number] = {
            "numero": from_number,
            "historique": [],
            "premiere_contact": datetime.now().isoformat()
        }

    client_data = db["clients"][from_number]
    client_data["historique"].append({"role": "user", "content": message_body})
    historique_recent = client_data["historique"][-10:]

    boutique_id = from_number.replace("whatsapp:+", "")
    boutique = db.get("boutiques", {}).get(boutique_id)

    # Vérifier si la boutique est active
    if boutique:
        active, raison = boutique_active(boutique)
        if not active:
            if raison == "bloque":
                msg = "⛔ Ce service est temporairement suspendu. Contactez le propriétaire."
            else:
                msg = "⏰ L'abonnement de cette boutique a expiré. Contactez le propriétaire pour le renouvellement."
            resp = MessagingResponse()
            resp.message(msg)
            return str(resp)

        prompt = f"""
Tu es Amina, assistante commerciale de {boutique['nom_boutique']} à {boutique['ville']}, Burkina Faso.
Tu réponds en français chaleureux style Afrique de l'Ouest.

Produits disponibles:
{boutique['produits']}

{boutique.get('message_perso', '')}

Quand le client veut commander, collecte:
- NOM COMPLET
- PRODUIT commandé
- ADRESSE de livraison
- NUMÉRO MOBILE MONEY
- MONTANT total

Quand tu as tout, termine avec:
[PRET_PAIEMENT:nom|produit|adresse|numero|montant]
"""
    else:
        prompt = PROMPT_DEFAULT

    reponse_ia = ask_groq(historique_recent, prompt)
    reponse_finale = reponse_ia

    if "[PRET_PAIEMENT:" in reponse_ia:
        try:
            debut = reponse_ia.index("[PRET_PAIEMENT:") + len("[PRET_PAIEMENT:")
            fin = reponse_ia.index("]", debut)
            infos = reponse_ia[debut:fin].split("|")

            nom     = sanitize(infos[0]) if len(infos) > 0 else "Client"
            produit = sanitize(infos[1]) if len(infos) > 1 else "Commande"
            adresse = sanitize(infos[2]) if len(infos) > 2 else "Non précisée"
            numero  = sanitize(infos[3]) if len(infos) > 3 else ""
            montant_str = infos[4] if len(infos) > 4 else "0"
            montant = int(re.sub(r'[^0-9]', '', montant_str) or 0)

            transaction_id = f"CMD_{int(datetime.now().timestamp())}"
            paiement = creer_lien_paiement(transaction_id, montant, nom, numero)

            db["commandes"].append({
                "transaction_id": transaction_id,
                "client": from_number,
                "boutique_id": boutique_id,
                "nom": nom,
                "produit": produit,
                "adresse": adresse,
                "numero_mobile_money": numero,
                "montant": montant,
                "statut": "EN_ATTENTE",
                "date": datetime.now().isoformat()
            })

            texte = reponse_ia.split("[PRET_PAIEMENT:")[0].strip()

            if paiement["success"]:
                reponse_finale = (
                    f"{texte}\n\n"
                    f"✅ *Commande enregistrée !*\n"
                    f"👤 {nom}\n"
                    f"🛍️ {produit}\n"
                    f"📍 {adresse}\n"
                    f"💰 {montant:,} FCFA\n\n"
                    f"🔗 *Payez ici:*\n{paiement['lien']}\n\n"
                    f"Merci de votre confiance 🙏"
                )
            else:
                reponse_finale = f"{texte}\n\n⚠️ Problème de paiement. Contactez-nous directement."

        except Exception as e:
            print(f"[ERREUR PAIEMENT] {e}")

    client_data["historique"].append({"role": "assistant", "content": reponse_finale})
    client_data["derniere_activite"] = datetime.now().isoformat()
    save_db(db)

    resp = MessagingResponse()
    resp.message(reponse_finale)
    return str(resp)

# =============================================
# WEBHOOK PAIEMENT CINETPAY
# =============================================
@app.route("/webhook/paiement", methods=["POST"])
def webhook_paiement():
    data = request.json or request.form.to_dict()
    transaction_id = data.get("cpm_trans_id") or data.get("transaction_id")

    if not transaction_id:
        return jsonify({"status": "error"}), 400

    db = load_db()
    for commande in db["commandes"]:
        if commande["transaction_id"] == transaction_id:
            commande["statut"] = "ACCEPTED"
            commande["date_paiement"] = datetime.now().isoformat()
            envoyer_whatsapp(
                commande["client"],
                f"🎉 *Paiement confirmé !*\n\n"
                f"Merci {commande['nom']} 🙏\n"
                f"🛍️ {commande.get('produit', 'Votre commande')}\n"
                f"💰 {commande['montant']:,} FCFA ✅\n\n"
                f"📦 Livraison à: {commande.get('adresse', 'En cours')}\n"
                f"Nous vous contacterons bientôt."
            )
            break

    save_db(db)
    return jsonify({"status": "ok"})

# =============================================
# ONBOARDING - SOUMETTRE
# =============================================
@app.route("/submit-onboarding", methods=["POST"])
def submit_onboarding():
    data = request.json

    whatsapp = data.get('whatsapp', '')
    orange   = data.get('orange_money', '')
    email    = data.get('email', '')

    if not valider_numero(whatsapp):
        return jsonify({"status": "error", "message": "Numéro WhatsApp invalide"}), 400
    if not valider_numero(orange):
        return jsonify({"status": "error", "message": "Numéro Mobile Money invalide"}), 400
    if not valider_email(email):
        return jsonify({"status": "error", "message": "Email invalide"}), 400

    db = load_db()
    boutique_id = whatsapp.replace('+', '').replace(' ', '')

    date_inscription = datetime.now()
    date_expiration = date_inscription + timedelta(days=DUREE_ABONNEMENT_JOURS)

    db["boutiques"][boutique_id] = {
        "nom_boutique": sanitize(data.get('nom_boutique', '')),
        "ville": sanitize(data.get('ville', '')),
        "produits": sanitize(data.get('produits', '')),
        "orange_money": orange,
        "email": email,
        "message_perso": sanitize(data.get('message_perso', '')),
        "whatsapp": whatsapp,
        "date_inscription": date_inscription.isoformat(),
        "date_expiration": date_expiration.isoformat(),
        "statut": "actif"
    }
    save_db(db)

    envoyer_whatsapp(
        MON_NUMERO,
        f"🆕 *Nouvelle boutique !*\n\n"
        f"🏪 {data.get('nom_boutique')}\n"
        f"📍 {data.get('ville')}\n"
        f"📱 {whatsapp}\n"
        f"💰 Mobile Money: {orange}\n"
        f"🛍️ {data.get('produits')}\n"
        f"📅 Expire le: {date_expiration.strftime('%d/%m/%Y')}\n"
        f"✅ PAIEMENT CONFIRMÉ - {PRIX_ABONNEMENT:,} FCFA"
    )

    return jsonify({
        "status": "ok",
        "boutique_id": boutique_id,
        "dashboard_url": f"{APP_URL}/dashboard/{boutique_id}",
        "date_expiration": date_expiration.strftime('%d/%m/%Y')
    })

# =============================================
# ADMIN - BLOQUER/ACTIVER BOUTIQUE
# =============================================
@app.route("/admin/boutique/<boutique_id>/bloquer", methods=["POST"])
def bloquer_boutique(boutique_id):
    token = request.args.get("token", "")
    if token != ADMIN_TOKEN:
        return jsonify({"status": "error"}), 403

    db = load_db()
    if boutique_id in db["boutiques"]:
        db["boutiques"][boutique_id]["statut"] = "bloque"
        save_db(db)
        whatsapp = db["boutiques"][boutique_id].get("whatsapp", "")
        envoyer_whatsapp(
            f"whatsapp:{whatsapp}",
            f"⛔ Votre boutique {db['boutiques'][boutique_id]['nom_boutique']} a été suspendue.\nContactez le support pour plus d'informations."
        )
        return jsonify({"status": "ok", "message": "Boutique bloquée"})
    return jsonify({"status": "error"}), 404

@app.route("/admin/boutique/<boutique_id>/activer", methods=["POST"])
def activer_boutique(boutique_id):
    token = request.args.get("token", "")
    if token != ADMIN_TOKEN:
        return jsonify({"status": "error"}), 403

    db = load_db()
    if boutique_id in db["boutiques"]:
        db["boutiques"][boutique_id]["statut"] = "actif"
        date_expiration = datetime.now() + timedelta(days=DUREE_ABONNEMENT_JOURS)
        db["boutiques"][boutique_id]["date_expiration"] = date_expiration.isoformat()
        save_db(db)
        whatsapp = db["boutiques"][boutique_id].get("whatsapp", "")
        envoyer_whatsapp(
            f"whatsapp:{whatsapp}",
            f"✅ Votre boutique {db['boutiques'][boutique_id]['nom_boutique']} est maintenant active !\n"
            f"Abonnement valide jusqu'au {date_expiration.strftime('%d/%m/%Y')} 🎉"
        )
        return jsonify({"status": "ok", "message": "Boutique activée"})
    return jsonify({"status": "error"}), 404

# =============================================
# DASHBOARD CLIENT
# =============================================
DASHBOARD_CLIENT_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ boutique.nom_boutique }} - Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
  :root { --vert:#25D366; --noir:#0D0D0D; --gris:#1A1A1A; --gris2:#2A2A2A; --texte:#F0F0F0; --gold:#FFD700; --rouge:#FF4444; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--noir); color:var(--texte); font-family:'Plus Jakarta Sans',sans-serif; padding:20px; }
  .header { text-align:center; padding:24px 0 32px; }
  .logo { width:56px;height:56px;background:var(--vert);border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:28px;margin:0 auto 12px; }
  h1 { font-size:1.5rem;font-weight:800; }
  .badge { display:inline-block;padding:4px 12px;border-radius:100px;font-size:0.75rem;margin-top:8px; }
  .badge.actif { background:rgba(37,211,102,.15);color:var(--vert);border:1px solid rgba(37,211,102,.3); }
  .badge.expire { background:rgba(255,68,68,.15);color:var(--rouge);border:1px solid rgba(255,68,68,.3); }
  .badge.bloque { background:rgba(255,68,68,.15);color:var(--rouge);border:1px solid rgba(255,68,68,.3); }
  .abonnement-card { border-radius:16px;padding:16px;margin-bottom:20px;text-align:center; }
  .abonnement-card.ok { background:rgba(37,211,102,.08);border:1px solid rgba(37,211,102,.2); }
  .abonnement-card.warn { background:rgba(255,214,0,.08);border:1px solid rgba(255,214,0,.2); }
  .abonnement-card.danger { background:rgba(255,68,68,.08);border:1px solid rgba(255,68,68,.2); }
  .stats { display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0; }
  .stat { background:var(--gris);border-radius:16px;padding:20px;border:1px solid var(--gris2); }
  .stat .label { font-size:0.72rem;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px; }
  .stat .value { font-size:1.8rem;font-weight:800; }
  .stat.vert .value { color:var(--vert); }
  .stat.gold .value { color:var(--gold); }
  .numero-card { background:var(--gris);border-radius:16px;padding:20px;border:2px solid var(--vert);margin-bottom:20px;text-align:center; }
  .numero-card .numero { font-size:1.4rem;font-weight:800;color:var(--vert); }
  .numero-card .hint { font-size:0.75rem;color:#666;margin-top:8px; }
  .section-title { font-size:0.8rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#888;margin:20px 0 12px; }
  .commande { background:var(--gris);border-radius:12px;padding:16px;margin-bottom:10px;border:1px solid var(--gris2); }
  .commande .top { display:flex;justify-content:space-between;align-items:flex-start; }
  .commande .nom { font-weight:700;font-size:0.95rem; }
  .commande .produit { color:#aaa;font-size:0.82rem;margin-top:2px; }
  .commande .adresse { color:#666;font-size:0.78rem;margin-top:4px; }
  .commande .date { color:#555;font-size:0.72rem;margin-top:2px; }
  .commande .montant { font-weight:800;color:var(--vert);white-space:nowrap; }
  .tag { display:inline-block;padding:3px 10px;border-radius:100px;font-size:0.7rem;font-weight:600;margin-top:4px; }
  .tag.ok { background:rgba(37,211,102,.15);color:var(--vert); }
  .tag.wait { background:rgba(255,214,0,.15);color:var(--gold); }
  .empty { text-align:center;padding:40px;color:#555; }
  .btn-refresh { width:100%;background:var(--vert);color:#000;border:none;border-radius:12px;padding:14px;font-family:'Plus Jakarta Sans',sans-serif;font-size:0.9rem;font-weight:700;cursor:pointer;margin-top:16px; }
</style>
</head>
<body>
<div class="header">
  <div class="logo">💬</div>
  <h1>{{ boutique.nom_boutique }}</h1>
  <span class="badge {{ statut }}">
    {% if statut == 'actif' %}● EN LIGNE{% elif statut == 'bloque' %}⛔ SUSPENDU{% else %}⏰ EXPIRÉ{% endif %}
  </span>
</div>

{% if statut == 'actif' %}
  {% if jours_restants <= 5 %}
  <div class="abonnement-card warn">
    <div style="font-size:0.8rem;color:#FFD700">⚠️ Abonnement expire dans {{ jours_restants }} jours</div>
    <div style="font-size:0.75rem;color:#888;margin-top:4px">Renouvelez pour continuer à recevoir des commandes</div>
  </div>
  {% else %}
  <div class="abonnement-card ok">
    <div style="font-size:0.8rem;color:#25D366">✅ Abonnement actif · {{ jours_restants }} jours restants</div>
    <div style="font-size:0.75rem;color:#888;margin-top:4px">Expire le {{ date_expiration }}</div>
  </div>
  {% endif %}
{% elif statut == 'expire' %}
<div class="abonnement-card danger">
  <div style="font-size:0.9rem;color:#FF4444;font-weight:700">⏰ Abonnement expiré</div>
  <div style="font-size:0.78rem;color:#888;margin-top:4px">Contactez-nous pour renouveler votre abonnement</div>
</div>
{% elif statut == 'bloque' %}
<div class="abonnement-card danger">
  <div style="font-size:0.9rem;color:#FF4444;font-weight:700">⛔ Boutique suspendue</div>
  <div style="font-size:0.78rem;color:#888;margin-top:4px">Contactez le support pour débloquer</div>
</div>
{% endif %}

<div class="numero-card">
  <div style="font-size:0.8rem;color:#888;margin-bottom:8px">Votre numéro WhatsApp Bot</div>
  <div class="numero">+1 415 523 8886</div>
  <div class="hint">Partagez ce numéro à vos clients 👆</div>
</div>

<div class="stats">
  <div class="stat">
    <div class="label">Commandes</div>
    <div class="value">{{ total_commandes }}</div>
  </div>
  <div class="stat vert">
    <div class="label">Payées</div>
    <div class="value">{{ payees }}</div>
  </div>
  <div class="stat gold">
    <div class="label">Revenus</div>
    <div class="value" style="font-size:1.2rem">{{ revenus }}</div>
  </div>
  <div class="stat">
    <div class="label">En attente</div>
    <div class="value">{{ en_attente }}</div>
  </div>
</div>

<div class="section-title">Commandes récentes</div>

{% if commandes %}
  {% for c in commandes|reverse %}
  <div class="commande">
    <div class="top">
      <div>
        <div class="nom">{{ c.nom }}</div>
        <div class="produit">🛍️ {{ c.get('produit', 'Commande') }}</div>
        <div class="adresse">📍 {{ c.get('adresse', 'Non précisée') }}</div>
        <div class="date">{{ c.date[:16].replace('T',' ') }}</div>
      </div>
      <div style="text-align:right">
        <div class="montant">{{ "{:,}".format(c.montant) }} F</div>
        {% if c.statut == 'ACCEPTED' %}
          <span class="tag ok">✓ Payé</span>
        {% else %}
          <span class="tag wait">⏳ Attente</span>
        {% endif %}
      </div>
    </div>
  </div>
  {% endfor %}
{% else %}
  <div class="empty">Aucune commande pour l'instant 🕐</div>
{% endif %}

<button class="btn-refresh" onclick="location.reload()">↻ Actualiser</button>
</body>
</html>
"""

@app.route("/dashboard/<boutique_id>")
def dashboard_client(boutique_id):
    db = load_db()
    boutique = db["boutiques"].get(boutique_id)

    if not boutique:
        return "<h2 style='color:red;text-align:center;padding:40px'>Boutique introuvable</h2>", 404

    commandes = [c for c in db["commandes"] if c.get("boutique_id") == boutique_id]
    payees = sum(1 for c in commandes if c["statut"] == "ACCEPTED")
    en_attente = sum(1 for c in commandes if c["statut"] == "EN_ATTENTE")
    revenus = sum(c["montant"] for c in commandes if c["statut"] == "ACCEPTED")

    active, statut = boutique_active(boutique)
    jours = jours_restants(boutique)

    exp_str = boutique.get("date_expiration", "")
    date_exp_affichage = ""
    if exp_str:
        date_exp_affichage = datetime.fromisoformat(exp_str).strftime('%d/%m/%Y')

    return render_template_string(
        DASHBOARD_CLIENT_HTML,
        boutique=boutique,
        commandes=commandes,
        total_commandes=len(commandes),
        payees=payees,
        en_attente=en_attente,
        revenus=f"{revenus:,} FCFA",
        statut=boutique.get("statut", "actif"),
        jours_restants=jours,
        date_expiration=date_exp_affichage
    )

# =============================================
# DASHBOARD ADMIN
# =============================================
ADMIN_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin - WhatsApp CRM</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
  :root { --vert:#25D366; --noir:#0D0D0D; --gris:#1A1A1A; --gris2:#2A2A2A; --texte:#F0F0F0; --gold:#FFD700; --rouge:#FF4444; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--noir); color:var(--texte); font-family:'Plus Jakarta Sans',sans-serif; padding:20px; }
  .header { text-align:center; padding:24px 0 32px; }
  h1 { font-size:1.5rem;font-weight:800; }
  h1 span { color:var(--vert); }
  .stats { display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:20px 0; }
  .stat { background:var(--gris);border-radius:16px;padding:20px;border:1px solid var(--gris2); }
  .stat .label { font-size:0.72rem;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px; }
  .stat .value { font-size:1.8rem;font-weight:800; }
  .stat.vert .value { color:var(--vert); }
  .stat.gold .value { color:var(--gold); }
  .stat.rouge .value { color:var(--rouge); }
  .section-title { font-size:0.8rem;font-weight:700;text-transform:uppercase;color:#888;margin:20px 0 12px; }
  .boutique-card { background:var(--gris);border-radius:16px;padding:16px;margin-bottom:12px;border:1px solid var(--gris2); }
  .boutique-card.bloque { border-color:rgba(255,68,68,.3); }
  .boutique-card.expire { border-color:rgba(255,214,0,.3); }
  .boutique-card .nom { font-size:1rem;font-weight:700; }
  .boutique-card .info { font-size:0.78rem;color:#888;margin-top:4px; }
  .boutique-card .stats-row { display:flex;gap:16px;margin-top:10px; }
  .boutique-card .stat-item { font-size:0.8rem;color:#888; }
  .boutique-card .stat-item span { color:var(--vert);font-weight:700; }
  .actions { display:flex;gap:8px;margin-top:12px;flex-wrap:wrap; }
  .btn { padding:8px 14px;border-radius:100px;font-family:'Plus Jakarta Sans',sans-serif;font-size:0.78rem;font-weight:700;cursor:pointer;border:none;transition:opacity .2s; }
  .btn:hover { opacity:.8; }
  .btn-view { background:rgba(37,211,102,.15);color:var(--vert);text-decoration:none;display:inline-flex;align-items:center; }
  .btn-block { background:rgba(255,68,68,.15);color:var(--rouge); }
  .btn-activate { background:rgba(37,211,102,.15);color:var(--vert); }
  .status-badge { display:inline-block;padding:3px 10px;border-radius:100px;font-size:0.7rem;font-weight:700;margin-left:8px; }
  .status-badge.actif { background:rgba(37,211,102,.15);color:var(--vert); }
  .status-badge.bloque { background:rgba(255,68,68,.15);color:var(--rouge); }
  .status-badge.expire { background:rgba(255,214,0,.15);color:var(--gold); }
  .btn-refresh { width:100%;background:var(--vert);color:#000;border:none;border-radius:12px;padding:14px;font-family:'Plus Jakarta Sans',sans-serif;font-size:0.9rem;font-weight:700;cursor:pointer;margin-top:16px; }
</style>
</head>
<body>
<div class="header">
  <h1>Admin <span>CRM</span></h1>
  <p style="color:#666;font-size:0.85rem;margin-top:4px">Tableau de bord propriétaire</p>
</div>

<div class="stats">
  <div class="stat">
    <div class="label">Boutiques actives</div>
    <div class="value">{{ total_actives }}</div>
  </div>
  <div class="stat vert">
    <div class="label">Commandes total</div>
    <div class="value">{{ total_commandes }}</div>
  </div>
  <div class="stat gold">
    <div class="label">Revenus clients</div>
    <div class="value" style="font-size:1.1rem">{{ revenus_total }}</div>
  </div>
  <div class="stat rouge">
    <div class="label">Expirées/Bloquées</div>
    <div class="value">{{ total_inactives }}</div>
  </div>
</div>

<div class="section-title">Mes boutiques ({{ total_boutiques }})</div>

{% for id, b in boutiques.items() %}
<div class="boutique-card {{ b.statut }}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div class="nom">
        {{ b.nom_boutique }}
        <span class="status-badge {{ b.statut }}">{{ b.statut }}</span>
      </div>
      <div class="info">📍 {{ b.ville }} · 📱 {{ b.whatsapp }}</div>
      <div class="info">📧 {{ b.email }}</div>
      <div class="info">📅 Expire: {{ b.date_exp_affichage }} · ⏳ {{ b.jours_restants }}j</div>
    </div>
  </div>
  <div class="stats-row">
    <div class="stat-item">Commandes: <span>{{ b.nb_commandes }}</span></div>
    <div class="stat-item">Revenus: <span>{{ b.revenus }} F</span></div>
  </div>
  <div class="actions">
    <a class="btn btn-view" href="/dashboard/{{ id }}">Voir dashboard</a>
    {% if b.statut == 'actif' %}
    <button class="btn btn-block" onclick="bloquer('{{ id }}')">⛔ Bloquer</button>
    {% else %}
    <button class="btn btn-activate" onclick="activer('{{ id }}')">✅ Activer</button>
    {% endif %}
  </div>
</div>
{% else %}
<p style="text-align:center;color:#555;padding:40px">Aucune boutique pour l'instant</p>
{% endfor %}

<button class="btn-refresh" onclick="location.reload()">↻ Actualiser</button>

<script>
const token = new URLSearchParams(window.location.search).get('token');

async function bloquer(id) {
  if (!confirm('Bloquer cette boutique ?')) return;
  await fetch(`/admin/boutique/${id}/bloquer?token=${token}`, {method:'POST'});
  location.reload();
}

async function activer(id) {
  if (!confirm('Activer/Renouveler cette boutique pour 30 jours ?')) return;
  await fetch(`/admin/boutique/${id}/activer?token=${token}`, {method:'POST'});
  location.reload();
}
</script>
</body>
</html>
"""

@app.route("/admin")
def admin():
    token = request.args.get("token", "")
    if token != ADMIN_TOKEN:
        return "<h2 style='color:red;text-align:center;padding:40px'>⛔ Accès refusé</h2>", 403

    db = load_db()
    boutiques = db.get("boutiques", {})
    commandes = db.get("commandes", [])

    boutiques_stats = {}
    for bid, b in boutiques.items():
        cmds = [c for c in commandes if c.get("boutique_id") == bid]
        revenus = sum(c["montant"] for c in cmds if c["statut"] == "ACCEPTED")
        jours = jours_restants(b)
        exp_str = b.get("date_expiration", "")
        date_exp = datetime.fromisoformat(exp_str).strftime('%d/%m/%Y') if exp_str else "N/A"
        boutiques_stats[bid] = {
            **b,
            "nb_commandes": len(cmds),
            "revenus": f"{revenus:,}",
            "jours_restants": jours,
            "date_exp_affichage": date_exp
        }

    total_payees = sum(1 for c in commandes if c["statut"] == "ACCEPTED")
    revenus_total = sum(c["montant"] for c in commandes if c["statut"] == "ACCEPTED")
    total_actives = sum(1 for b in boutiques.values() if b.get("statut") == "actif")
    total_inactives = len(boutiques) - total_actives

    return render_template_string(
        ADMIN_HTML,
        boutiques=boutiques_stats,
        total_boutiques=len(boutiques),
        total_commandes=len(commandes),
        total_payees=total_payees,
        revenus_total=f"{revenus_total:,} FCFA",
        total_actives=total_actives,
        total_inactives=total_inactives
    )

# =============================================
# PAGE MERCI
# =============================================
@app.route("/merci")
def merci():
    return """
    <html><body style="background:#0D0D0D;color:#F0F0F0;font-family:sans-serif;text-align:center;padding:60px 20px">
    <div style="font-size:3rem">🎉</div>
    <h1 style="color:#25D366;margin:16px 0">Paiement réussi !</h1>
    <p>Merci pour votre commande.</p>
    <p style="margin-top:8px;color:#666">Vous recevrez une confirmation sur WhatsApp.</p>
    </body></html>
    """

# =============================================
# ONBOARDING
# =============================================
@app.route("/onboarding")
def onboarding():
    return send_from_directory('.', 'onboarding.html')

# =============================================
# INDEX
# =============================================
@app.route("/")
def index():
    return jsonify({
        "status": "✅ WhatsApp CRM SaaS - En ligne",
        "version": "3.0",
        "endpoints": {
            "/onboarding": "Créer une boutique",
            "/dashboard/<id>": "Dashboard client",
            "/admin?token=XXX": "Panel admin",
            "/webhook/whatsapp": "Webhook Twilio",
            "/webhook/paiement": "Webhook CinetPay",
            "/health": "Health check"
        }
    })

# =============================================
# LANCEMENT
# =============================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
ENDOFFILE
