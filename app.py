"""
=====================================
  WhatsApp CRM SaaS - Version 3.2
  Multi-boutiques | Admin | Abonnement
  Blocage | Notifications | Production
  Green API (WhatsApp personnel)
=====================================
"""

import os
import json
import re
import requests
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "whatsapp-crm-secret-2024")

# =============================================
# CONFIG
# =============================================
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

GREEN_API_ID_INSTANCE    = os.getenv("GREEN_API_ID_INSTANCE")
GREEN_API_TOKEN_INSTANCE = os.getenv("GREEN_API_TOKEN_INSTANCE")
GREEN_API_PARTNER_TOKEN  = os.getenv("GREEN_API_PARTNER_TOKEN")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin123")
MON_NUMERO  = os.getenv("MON_NUMERO", "22675000000")
APP_URL     = os.getenv("APP_URL", "https://hope-to-million.onrender.com")

PRIX_ABONNEMENT        = 50000
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

def formater_numero_green(numero):
    propre = re.sub(r'[^\d]', '', numero)
    return f"{propre}@c.us"

# =============================================
# GREEN API - ENVOI MESSAGES
# =============================================
def envoyer_whatsapp(numero_dest, message, id_instance=None, token_instance=None):
    iid   = id_instance    or GREEN_API_ID_INSTANCE
    token = token_instance or GREEN_API_TOKEN_INSTANCE

    if not iid or not token:
        print(f"[GREEN API] Credentials manquants pour {numero_dest}")
        return False

    chat_id = formater_numero_green(numero_dest)
    url = f"https://api.green-api.com/waInstance{iid}/sendMessage/{token}"

    try:
        resp = requests.post(url, json={"chatId": chat_id, "message": message}, timeout=20)
        resp.raise_for_status()
        print(f"[GREEN API] Message envoyé à {numero_dest}")
        return True
    except Exception as e:
        print(f"[ERREUR GREEN API] {e}")
        return False

# =============================================
# GREEN API - CRÉER INSTANCE (si partner token dispo)
# =============================================
def creer_instance_green_api():
    if not GREEN_API_PARTNER_TOKEN:
        return None
    url = "https://api.green-api.com/partner/createInstance/accountId"
    try:
        resp = requests.post(
            url,
            json={"stateWebhook": True, "incomingWebhook": True},
            headers={"Authorization": f"Bearer {GREEN_API_PARTNER_TOKEN}"},
            timeout=20
        )
        data = resp.json()
        if data.get("idInstance"):
            return {
                "idInstance": str(data["idInstance"]),
                "apiTokenInstance": data["apiTokenInstance"]
            }
        return None
    except Exception as e:
        print(f"[ERREUR GREEN API] Création instance: {e}")
        return None

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
        iid   = boutique.get("id_instance")
        token = boutique.get("api_token_instance")

        if jours == 3:
            envoyer_whatsapp(
                whatsapp,
                f"⚠️ *Rappel abonnement*\n\nBonjour {boutique['nom_boutique']} !\n"
                f"Votre abonnement expire dans *3 jours*.\n"
                f"💰 Renouvellement: *{PRIX_ABONNEMENT:,} FCFA/mois*",
                iid, token
            )
            envoyer_whatsapp(MON_NUMERO, f"⚠️ Boutique {boutique['nom_boutique']} expire dans 3 jours !")

        if jours == 0 and boutique.get("statut") == "actif":
            db["boutiques"][bid]["statut"] = "expire"
            envoyer_whatsapp(
                whatsapp,
                f"🔴 *Abonnement expiré*\n\nBonjour {boutique['nom_boutique']} !\n"
                f"Amina ne répond plus à vos clients.\n"
                f"Renouvelez: *{PRIX_ABONNEMENT:,} FCFA/mois*",
                iid, token
            )
            envoyer_whatsapp(MON_NUMERO, f"🔴 Boutique {boutique['nom_boutique']} - abonnement EXPIRÉ !")

    save_db(db)

# =============================================
# IA GROQ
# =============================================
PROMPT_DEFAULT = """
Tu es Amina, une assistante commerciale virtuelle au Burkina Faso.
Tu réponds en français chaleureux style Afrique de l'Ouest.
Quand le client veut commander, collecte dans cet ordre:
1. NOM COMPLET
2. PRODUIT commandé
3. NUMÉRO MOBILE MONEY
4. MONTANT total
5. LOCALISATION: demande-lui d'envoyer sa localisation WhatsApp (bouton 📎 → Localisation).
Quand tu as tout: [PRET_PAIEMENT:nom|produit|adresse|numero|montant]
"""

def ask_groq(messages, system_prompt):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 500,
        "messages": [{"role": "system", "content": system_prompt}] + messages
    }
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[ERREUR GROQ] {e}")
        return "Désolé, je rencontre un problème technique. Réessaie dans un instant 🙏"

# =============================================
# CINETPAY
# =============================================
def creer_lien_paiement(transaction_id, montant, nom, tel):
    try:
        payload = {
            "apikey": CINETPAY_API_KEY, "site_id": CINETPAY_SITE_ID,
            "transaction_id": transaction_id, "amount": montant, "currency": "XOF",
            "description": f"Commande - {nom}",
            "return_url": f"{APP_URL}/merci", "notify_url": f"{APP_URL}/webhook/paiement",
            "customer_name": nom, "customer_phone_number": tel,
            "channels": "MOBILE_MONEY", "lang": "fr"
        }
        resp = requests.post("https://api-checkout.cinetpay.com/v2/payment", json=payload, timeout=20)
        data = resp.json()
        if data.get("code") == "201":
            return {"success": True, "lien": data["data"]["payment_url"]}
        return {"success": False, "erreur": data.get("message")}
    except Exception as e:
        return {"success": False, "erreur": str(e)}

# =============================================
# HEALTH CHECK
# =============================================
@app.route("/health")
def health():
    verifier_expirations()
    return jsonify({"status": "ok"})

# =============================================
# PAGE ACCUEIL
# =============================================
@app.route("/")
def index():
    with open("onboarding.html", "r", encoding="utf-8") as f:
        return f.read()

# =============================================
# WEBHOOK GREEN API ENTRANT
# =============================================
@app.route("/webhook/green-api/<boutique_id>", methods=["POST"])
def webhook_green_api(boutique_id):
    data = request.json or {}
    if data.get("typeWebhook") != "incomingMessageReceived":
        return jsonify({"status": "ok"})

    sender_data  = data.get("senderData", {})
    from_number  = sender_data.get("sender", "").replace("@c.us", "")
    if not from_number.startswith("+"):
        from_number = "+" + from_number

    message_data = data.get("messageData", {})
    message_type = message_data.get("typeMessage", "")

    # Détecter la localisation WhatsApp
    localisation_text = None
    if message_type == "locationMessage":
        loc  = message_data.get("locationMessageData", {})
        lat  = loc.get("latitude")
        lng  = loc.get("longitude")
        name = loc.get("nameLocation", "")
        if lat and lng:
            maps_url = f"https://maps.google.com/?q={lat},{lng}"
            localisation_text = f"[LOCALISATION:{lat}|{lng}|{maps_url}]"
            message_body = f"Voici ma localisation : {maps_url}" + (f" ({name})" if name else "")
        else:
            return jsonify({"status": "ok"})
    else:
        message_body = sanitize(message_data.get("textMessageData", {}).get("textMessage", "").strip())
        if not message_body:
            return jsonify({"status": "ok"})

    db = load_db()
    client_key = f"{boutique_id}_{from_number}"
    if client_key not in db["clients"]:
        db["clients"][client_key] = {"numero": from_number, "boutique_id": boutique_id, "historique": [], "premiere_contact": datetime.now().isoformat()}

    client_data = db["clients"][client_key]

    # Stocker la localisation dans le profil client si reçue
    if localisation_text:
        loc_parts = localisation_text.replace("[LOCALISATION:", "").replace("]", "").split("|")
        if len(loc_parts) >= 3:
            client_data["localisation"] = {
                "latitude":  loc_parts[0],
                "longitude": loc_parts[1],
                "maps_url":  loc_parts[2],
                "date":      datetime.now().isoformat()
            }

    client_data["historique"].append({"role": "user", "content": message_body})
    historique_recent = client_data["historique"][-10:]

    boutique = db.get("boutiques", {}).get(boutique_id)

    if boutique:
        active, raison = boutique_active(boutique)
        if not active:
            msg = "⛔ Ce service est suspendu." if raison == "bloque" else "⏰ L'abonnement a expiré."
            envoyer_whatsapp(from_number, msg, boutique.get("id_instance"), boutique.get("api_token_instance"))
            return jsonify({"status": "ok"})

        prompt = f"""Tu es Amina, assistante de {boutique['nom_boutique']} à {boutique['ville']}, Burkina Faso.
Tu réponds en français chaleureux style Afrique de l'Ouest.
Produits: {boutique['produits']}
{boutique.get('message_perso', '')}
Quand le client commande, collecte dans cet ordre:
1. NOM COMPLET
2. PRODUIT commandé
3. NUMÉRO MOBILE MONEY
4. MONTANT total
5. LOCALISATION: demande-lui d'envoyer sa localisation WhatsApp (bouton 📎 → Localisation) pour la livraison. Si le client a déjà envoyé sa localisation, utilise-la directement.
Quand tu as tout (y compris la localisation): [PRET_PAIEMENT:nom|produit|adresse|numero|montant]"""
    else:
        prompt = PROMPT_DEFAULT

    reponse_ia = ask_groq(historique_recent, prompt)
    reponse_finale = reponse_ia

    if "[PRET_PAIEMENT:" in reponse_ia:
        try:
            debut  = reponse_ia.index("[PRET_PAIEMENT:") + len("[PRET_PAIEMENT:")
            fin    = reponse_ia.index("]", debut)
            infos  = reponse_ia[debut:fin].split("|")
            nom     = sanitize(infos[0]) if len(infos) > 0 else "Client"
            produit = sanitize(infos[1]) if len(infos) > 1 else "Commande"
            adresse = sanitize(infos[2]) if len(infos) > 2 else "Non précisée"
            numero  = sanitize(infos[3]) if len(infos) > 3 else ""
            montant = int(re.sub(r'[^0-9]', '', infos[4] if len(infos) > 4 else "0") or 0)

            transaction_id = f"CMD_{int(datetime.now().timestamp())}"
            paiement = creer_lien_paiement(transaction_id, montant, nom, numero)

            # Récupérer la localisation si disponible
            maps_url = client_data.get("localisation", {}).get("maps_url", "")
            adresse_finale = f"{adresse} 📍 {maps_url}" if maps_url else adresse

            db["commandes"].append({
                "transaction_id": transaction_id, "client": from_number,
                "boutique_id": boutique_id, "nom": nom, "produit": produit,
                "adresse": adresse_finale,
                "maps_url": maps_url,
                "numero_mobile_money": numero,
                "montant": montant, "statut": "EN_ATTENTE", "date": datetime.now().isoformat()
            })

            texte = reponse_ia.split("[PRET_PAIEMENT:")[0].strip()
            if paiement["success"]:
                reponse_finale = f"{texte}\n\n✅ *Commande enregistrée !*\n👤 {nom}\n🛍️ {produit}\n📍 {adresse}\n💰 {montant:,} FCFA\n\n🔗 *Payez ici:*\n{paiement['lien']}\n\nMerci 🙏"
            else:
                reponse_finale = f"{texte}\n\n⚠️ Problème de paiement. Contactez-nous directement."
        except Exception as e:
            print(f"[ERREUR PAIEMENT] {e}")

    envoyer_whatsapp(from_number, reponse_finale,
        boutique.get("id_instance") if boutique else None,
        boutique.get("api_token_instance") if boutique else None)

    client_data["historique"].append({"role": "assistant", "content": reponse_finale})
    client_data["derniere_activite"] = datetime.now().isoformat()
    save_db(db)
    return jsonify({"status": "ok"})

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
            boutique = db["boutiques"].get(commande["boutique_id"], {})
            envoyer_whatsapp(
                commande["client"],
                f"🎉 *Paiement confirmé !*\nMerci {commande['nom']} 🙏\n"
                f"🛍️ {commande.get('produit')}\n💰 {commande['montant']:,} FCFA ✅\n"
                f"📦 Livraison: {commande.get('adresse')}",
                boutique.get("id_instance"), boutique.get("api_token_instance")
            )
            break

    save_db(db)
    return jsonify({"status": "ok"})

# =============================================
# ONBOARDING
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
    boutique_id      = whatsapp.replace('+', '').replace(' ', '')
    date_inscription = datetime.now()
    date_expiration  = date_inscription + timedelta(days=DUREE_ABONNEMENT_JOURS)

    # Essaie de créer une instance auto si partner token dispo
    instance          = creer_instance_green_api()
    id_instance       = instance["idInstance"]       if instance else None
    api_token_instance = instance["apiTokenInstance"] if instance else None

    # Configure le webhook si instance créée
    if id_instance and api_token_instance:
        try:
            requests.post(
                f"https://api.green-api.com/waInstance{id_instance}/setSettings/{api_token_instance}",
                json={"incomingWebhook": "yes", "webhookUrl": f"{APP_URL}/webhook/green-api/{boutique_id}"},
                timeout=10
            )
        except Exception as e:
            print(f"[GREEN API] Erreur config webhook: {e}")

    db["boutiques"][boutique_id] = {
        "nom_boutique":       sanitize(data.get('nom_boutique', '')),
        "ville":              sanitize(data.get('ville', '')),
        "produits":           sanitize(data.get('produits', '')),
        "orange_money":       orange,
        "email":              email,
        "message_perso":      sanitize(data.get('message_perso', '')),
        "whatsapp":           whatsapp,
        "id_instance":        id_instance,
        "api_token_instance": api_token_instance,
        "date_inscription":   date_inscription.isoformat(),
        "date_expiration":    date_expiration.isoformat(),
        "statut":             "actif"
    }
    save_db(db)

    envoyer_whatsapp(
        MON_NUMERO,
        f"🆕 *Nouvelle boutique !*\n🏪 {data.get('nom_boutique')}\n📍 {data.get('ville')}\n"
        f"📱 {whatsapp}\n💰 {orange}\n📅 Expire: {date_expiration.strftime('%d/%m/%Y')}\n"
        f"✅ PAIEMENT - {PRIX_ABONNEMENT:,} FCFA/mois\n"
        f"{'⚠️ Instance à configurer manuellement' if not id_instance else '✅ Instance Green API créée'}"
    )

    return jsonify({
        "status":             "ok",
        "boutique_id":        boutique_id,
        "dashboard_url":      f"{APP_URL}/dashboard/{boutique_id}",
        "date_expiration":    date_expiration.strftime('%d/%m/%Y'),
        "idInstance":         id_instance,
        "apiTokenInstance":   api_token_instance
    })

# =============================================
# ADMIN - SET INSTANCE (flow manuel)
# =============================================
@app.route("/admin/boutique/<boutique_id>/set-instance", methods=["POST"])
def set_instance(boutique_id):
    token = request.args.get("token", "")
    if token != ADMIN_TOKEN:
        return jsonify({"status": "error"}), 403

    data               = request.json or {}
    id_instance        = data.get("idInstance")
    api_token_instance = data.get("apiTokenInstance")

    if not id_instance or not api_token_instance:
        return jsonify({"status": "error", "message": "idInstance et apiTokenInstance requis"}), 400

    db = load_db()
    if boutique_id not in db["boutiques"]:
        return jsonify({"status": "error", "message": "Boutique introuvable"}), 404

    db["boutiques"][boutique_id]["id_instance"]        = id_instance
    db["boutiques"][boutique_id]["api_token_instance"] = api_token_instance

    # Configure le webhook
    try:
        requests.post(
            f"https://api.green-api.com/waInstance{id_instance}/setSettings/{api_token_instance}",
            json={"incomingWebhook": "yes", "webhookUrl": f"{APP_URL}/webhook/green-api/{boutique_id}"},
            timeout=10
        )
        print(f"[GREEN API] Webhook configuré pour {boutique_id}")
    except Exception as e:
        print(f"[GREEN API] Erreur webhook: {e}")

    save_db(db)
    return jsonify({
        "status": "ok",
        "message": f"Instance configurée pour {boutique_id}",
        "qr_url": f"https://api.green-api.com/waInstance{id_instance}/qr/{api_token_instance}"
    })

# =============================================
# ADMIN - BLOQUER / ACTIVER
# =============================================
@app.route("/admin/boutique/<boutique_id>/bloquer", methods=["POST"])
def bloquer_boutique(boutique_id):
    if request.args.get("token") != ADMIN_TOKEN:
        return jsonify({"status": "error"}), 403
    db = load_db()
    if boutique_id not in db["boutiques"]:
        return jsonify({"status": "error"}), 404
    db["boutiques"][boutique_id]["statut"] = "bloque"
    save_db(db)
    b = db["boutiques"][boutique_id]
    envoyer_whatsapp(b.get("whatsapp",""), f"⛔ Boutique {b['nom_boutique']} suspendue.", b.get("id_instance"), b.get("api_token_instance"))
    return jsonify({"status": "ok"})

@app.route("/admin/boutique/<boutique_id>/activer", methods=["POST"])
def activer_boutique(boutique_id):
    if request.args.get("token") != ADMIN_TOKEN:
        return jsonify({"status": "error"}), 403
    db = load_db()
    if boutique_id not in db["boutiques"]:
        return jsonify({"status": "error"}), 404
    date_expiration = datetime.now() + timedelta(days=DUREE_ABONNEMENT_JOURS)
    db["boutiques"][boutique_id]["statut"] = "actif"
    db["boutiques"][boutique_id]["date_expiration"] = date_expiration.isoformat()
    save_db(db)
    b = db["boutiques"][boutique_id]
    envoyer_whatsapp(b.get("whatsapp",""), f"✅ Boutique {b['nom_boutique']} active jusqu'au {date_expiration.strftime('%d/%m/%Y')} 🎉", b.get("id_instance"), b.get("api_token_instance"))
    return jsonify({"status": "ok"})

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
  :root { --vert:#25D366;--noir:#0D0D0D;--gris:#1A1A1A;--gris2:#2A2A2A;--texte:#F0F0F0;--gold:#FFD700;--rouge:#FF4444; }
  * { margin:0;padding:0;box-sizing:border-box; }
  body { background:var(--noir);color:var(--texte);font-family:'Plus Jakarta Sans',sans-serif;padding:20px; }
  .header { text-align:center;padding:24px 0 32px; }
  .logo { width:56px;height:56px;background:var(--vert);border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:28px;margin:0 auto 12px; }
  h1 { font-size:1.5rem;font-weight:800; }
  .badge { display:inline-block;padding:4px 12px;border-radius:100px;font-size:0.75rem;margin-top:8px; }
  .badge.actif { background:rgba(37,211,102,.15);color:var(--vert);border:1px solid rgba(37,211,102,.3); }
  .badge.expire,.badge.bloque { background:rgba(255,68,68,.15);color:var(--rouge);border:1px solid rgba(255,68,68,.3); }
  .stats { display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0; }
  .stat { background:var(--gris);border-radius:16px;padding:20px;border:1px solid var(--gris2); }
  .stat .label { font-size:0.72rem;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px; }
  .stat .value { font-size:1.8rem;font-weight:800; }
  .stat.vert .value { color:var(--vert); }
  .stat.gold .value { color:var(--gold); }

  /* QR Card */
  .qr-card { background:var(--gris);border-radius:16px;padding:20px;border:2px solid rgba(37,211,102,.3);margin:16px 0;text-align:center; }
  .qr-card .qr-title { font-size:0.78rem;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:12px; }
  .qr-wrapper { background:#fff;border-radius:12px;padding:12px;display:inline-block;margin-bottom:12px; }
  .qr-wrapper img { width:180px;height:180px;display:block; }
  .qr-status { font-size:0.82rem;margin-bottom:10px; }
  .qr-status.connected { color:var(--vert);font-weight:700; }
  .qr-status.waiting { color:#888; }
  .btn-refresh { background:rgba(37,211,102,.1);border:1px solid rgba(37,211,102,.3);color:var(--vert);border-radius:10px;padding:8px 16px;font-family:'Plus Jakarta Sans',sans-serif;font-size:0.82rem;font-weight:600;cursor:pointer;transition:background .2s; }
  .btn-refresh:hover { background:rgba(37,211,102,.2); }
  .qr-hint { font-size:0.7rem;color:#444;margin-top:8px; }

  .section-title { font-size:0.8rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#888;margin:20px 0 12px; }
  .commande { background:var(--gris);border-radius:12px;padding:16px;margin-bottom:10px;border:1px solid var(--gris2); }
  .commande .top { display:flex;justify-content:space-between;align-items:flex-start; }
  .commande .nom { font-weight:700;font-size:0.95rem; }
  .commande .montant { color:var(--vert);font-weight:800; }
  .commande .detail { font-size:0.8rem;color:#888;margin-top:6px; }
  .badge-statut { font-size:0.7rem;padding:3px 8px;border-radius:100px; }
  .badge-statut.accepted { background:rgba(37,211,102,.15);color:var(--vert); }
  .badge-statut.en_attente { background:rgba(255,214,0,.15);color:var(--gold); }
  .no-instance { background:rgba(255,214,0,.08);border:1px solid rgba(255,214,0,.2);border-radius:12px;padding:16px;text-align:center;color:#888;font-size:0.85rem;margin:16px 0; }
</style>
</head>
<body>
<div class="header">
  <div class="logo">💬</div>
  <h1>{{ boutique.nom_boutique }}</h1>
  <span class="badge {{ boutique.statut }}">
    {% if boutique.statut == 'actif' %}✅ Actif{% elif boutique.statut == 'expire' %}⏰ Expiré{% else %}⛔ Suspendu{% endif %}
  </span>
</div>

<div class="stats">
  <div class="stat vert">
    <div class="label">Commandes</div>
    <div class="value">{{ commandes|length }}</div>
  </div>
  <div class="stat gold">
    <div class="label">Revenus (F)</div>
    <div class="value">{{ "{:,}".format(total_revenus) }}</div>
  </div>
</div>

{% if boutique.id_instance and boutique.api_token_instance %}
<div class="qr-card">
  <div class="qr-title">📱 Connexion WhatsApp</div>
  <div class="qr-wrapper">
    <img id="qr-img" src="" alt="QR Code" />
  </div>
  <div class="qr-status waiting" id="qr-status">⏳ Chargement...</div>
  <button class="btn-refresh" onclick="rafraichirQR()">🔄 Rafraîchir</button>
  <div class="qr-hint">Le QR expire toutes les 20 secondes</div>
</div>
{% else %}
<div class="no-instance">
  ⏳ Votre connexion WhatsApp est en cours de configuration.<br>
  Vous recevrez une notification dès que c'est prêt.
</div>
{% endif %}

<div class="section-title">Dernières commandes</div>
{% for cmd in commandes[-10:]|reverse %}
<div class="commande">
  <div class="top">
    <div class="nom">{{ cmd.nom }}</div>
    <div class="montant">{{ "{:,}".format(cmd.montant) }} F</div>
  </div>
  <div class="detail">🛍️ {{ cmd.produit }} · 
    {% if cmd.maps_url %}
    <a href="{{ cmd.maps_url }}" target="_blank" style="color:var(--vert)">📍 Voir sur Maps</a>
    {% else %}
    📍 {{ cmd.adresse }}
    {% endif %}
  </div>
  <div class="detail" style="margin-top:4px">
    <span class="badge-statut {{ cmd.statut.lower() }}">{{ cmd.statut }}</span>
    · {{ cmd.date[:10] }}
  </div>
</div>
{% else %}
<p style="color:#555;text-align:center;padding:20px">Aucune commande pour l'instant</p>
{% endfor %}

{% if boutique.id_instance and boutique.api_token_instance %}
<script>
  const ID_INSTANCE    = "{{ boutique.id_instance }}";
  const TOKEN_INSTANCE = "{{ boutique.api_token_instance }}";
  let pollingInterval  = null;

  async function rafraichirQR() {
    document.getElementById('qr-status').textContent = '⏳ Chargement...';
    document.getElementById('qr-status').className = 'qr-status waiting';
    try {
      const res  = await fetch(`https://api.green-api.com/waInstance${ID_INSTANCE}/qr/${TOKEN_INSTANCE}`);
      const data = await res.json();
      if (data.type === 'qrCode') {
        document.getElementById('qr-img').src = 'data:image/png;base64,' + data.message;
        document.getElementById('qr-status').textContent = '⏳ Scannez avec votre WhatsApp';
        document.getElementById('qr-status').className = 'qr-status waiting';
      } else if (data.type === 'alreadyLogged') {
        document.getElementById('qr-img').src = '';
        document.querySelector('.qr-wrapper').style.display = 'none';
        document.getElementById('qr-status').textContent = '✅ WhatsApp connecté !';
        document.getElementById('qr-status').className = 'qr-status connected';
        clearInterval(pollingInterval);
      }
    } catch(e) {
      document.getElementById('qr-status').textContent = '❌ Erreur de chargement';
    }
  }

  rafraichirQR();
  pollingInterval = setInterval(() => {
    if (!document.getElementById('qr-status').classList.contains('connected')) {
      rafraichirQR();
    }
  }, 20000);
</script>
{% endif %}
</body>
</html>
"""

@app.route("/dashboard/<boutique_id>")
def dashboard(boutique_id):
    db = load_db()
    b  = db["boutiques"].get(boutique_id)
    if not b:
        return "Boutique introuvable", 404
    commandes     = [c for c in db["commandes"] if c.get("boutique_id") == boutique_id]
    total_revenus = sum(c["montant"] for c in commandes if c.get("statut") == "ACCEPTED")
    return render_template_string(
        DASHBOARD_CLIENT_HTML,
        boutique=type('B', (), b)(),
        commandes=commandes,
        total_revenus=total_revenus
    )

# =============================================
# DASHBOARD ADMIN
# =============================================
ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin — Hope to Million</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
  :root { --vert:#25D366;--noir:#080B0A;--gris:#111512;--gris2:#1A1F1C;--gris3:#242926;--texte:#E8F0EB;--gold:#F5C842;--rouge:#FF4455;--bleu:#4FACFE; }
  * { margin:0;padding:0;box-sizing:border-box; }
  body { background:var(--noir);color:var(--texte);font-family:'Space Grotesk',sans-serif;min-height:100vh; }
  .sidebar { position:fixed;left:0;top:0;bottom:0;width:220px;background:var(--gris);border-right:1px solid var(--gris3);padding:28px 16px;display:flex;flex-direction:column;gap:4px;z-index:100; }
  .sidebar-logo { display:flex;align-items:center;gap:10px;padding:0 8px 24px;border-bottom:1px solid var(--gris3);margin-bottom:12px; }
  .sidebar-logo .icon { width:36px;height:36px;background:var(--vert);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px; }
  .sidebar-logo .name { font-size:0.85rem;font-weight:700; }
  .sidebar-logo .sub { font-size:0.65rem;color:#555;font-family:'Space Mono',monospace; }
  .nav-item { display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;font-size:0.85rem;font-weight:500;color:#666;transition:all .15s;text-decoration:none; }
  .nav-item:hover { background:var(--gris2);color:var(--texte); }
  .nav-item.active { background:rgba(37,211,102,.12);color:var(--vert); }
  .sidebar-footer { margin-top:auto;padding-top:16px;border-top:1px solid var(--gris3);font-size:0.72rem;color:#444;font-family:'Space Mono',monospace;padding-left:12px; }
  .main { margin-left:220px;padding:32px;min-height:100vh; }
  .topbar { display:flex;justify-content:space-between;align-items:center;margin-bottom:32px; }
  .topbar h1 { font-size:1.4rem;font-weight:700; }
  .topbar .date { font-size:0.78rem;color:#555;font-family:'Space Mono',monospace; }
  .kpi-grid { display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:32px; }
  .kpi { background:var(--gris);border-radius:16px;padding:20px;border:1px solid var(--gris3);position:relative;overflow:hidden; }
  .kpi::before { content:'';position:absolute;top:0;left:0;right:0;height:2px; }
  .kpi.vert::before{background:var(--vert);} .kpi.gold::before{background:var(--gold);} .kpi.rouge::before{background:var(--rouge);} .kpi.bleu::before{background:var(--bleu);}
  .kpi .label { font-size:0.72rem;color:#666;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px;font-family:'Space Mono',monospace; }
  .kpi .value { font-size:1.9rem;font-weight:700;line-height:1;margin-bottom:6px; }
  .kpi.vert .value{color:var(--vert);} .kpi.gold .value{color:var(--gold);} .kpi.rouge .value{color:var(--rouge);} .kpi.bleu .value{color:var(--bleu);}
  .kpi .sub { font-size:0.72rem;color:#555; }
  .section { background:var(--gris);border-radius:16px;border:1px solid var(--gris3);overflow:hidden;margin-bottom:24px; }
  .section-header { display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-bottom:1px solid var(--gris3); }
  .section-header h2 { font-size:0.9rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#888; }
  .badge-count { background:var(--gris3);color:var(--texte);border-radius:100px;padding:3px 10px;font-size:0.72rem;font-family:'Space Mono',monospace; }
  table { width:100%;border-collapse:collapse; }
  thead th { padding:12px 24px;text-align:left;font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;color:#555;background:var(--gris2);font-family:'Space Mono',monospace; }
  tbody tr { border-bottom:1px solid var(--gris3);transition:background .1s; }
  tbody tr:last-child{border-bottom:none;} tbody tr:hover{background:var(--gris2);}
  tbody td { padding:14px 24px;font-size:0.85rem;vertical-align:middle; }
  .boutique-name{font-weight:700;margin-bottom:2px;} .boutique-ville{font-size:0.72rem;color:#666;font-family:'Space Mono',monospace;}
  .statut-badge{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:100px;font-size:0.72rem;font-weight:600;}
  .statut-badge.actif{background:rgba(37,211,102,.12);color:var(--vert);border:1px solid rgba(37,211,102,.2);}
  .statut-badge.expire,.statut-badge.bloque{background:rgba(255,68,85,.12);color:var(--rouge);border:1px solid rgba(255,68,85,.2);}
  .instance-badge{font-size:0.68rem;padding:2px 8px;border-radius:6px;font-family:'Space Mono',monospace;}
  .instance-badge.ok{background:rgba(37,211,102,.12);color:var(--vert);}
  .instance-badge.missing{background:rgba(255,214,0,.12);color:var(--gold);}
  .expiration{font-family:'Space Mono',monospace;font-size:0.78rem;}
  .expiration.urgent{color:var(--rouge);} .expiration.warning{color:var(--gold);} .expiration.ok{color:#555;}
  .jours-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:0.68rem;font-family:'Space Mono',monospace;margin-left:6px;}
  .jours-badge.urgent{background:rgba(255,68,85,.15);color:var(--rouge);}
  .jours-badge.warning{background:rgba(245,200,66,.15);color:var(--gold);}
  .jours-badge.ok{background:var(--gris3);color:#666;}
  .actions{display:flex;gap:6px;flex-wrap:wrap;}
  .btn-action{padding:6px 12px;border-radius:8px;border:none;font-family:'Space Grotesk',sans-serif;font-size:0.75rem;font-weight:600;cursor:pointer;transition:opacity .15s;text-decoration:none;}
  .btn-action:hover{opacity:.75;}
  .btn-action.voir{background:var(--gris3);color:var(--texte);}
  .btn-action.bloquer{background:rgba(255,68,85,.15);color:var(--rouge);border:1px solid rgba(255,68,85,.2);}
  .btn-action.activer{background:rgba(37,211,102,.15);color:var(--vert);border:1px solid rgba(37,211,102,.2);}
  .btn-action.config{background:rgba(79,172,254,.15);color:var(--bleu);border:1px solid rgba(79,172,254,.2);}
  .revenu{font-family:'Space Mono',monospace;font-size:0.82rem;color:var(--gold);font-weight:700;}
  .empty{text-align:center;padding:48px;color:#444;font-size:0.85rem;}

  /* Modal config instance */
  .modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;align-items:center;justify-content:center;}
  .modal-overlay.open{display:flex;}
  .modal{background:var(--gris);border-radius:20px;padding:28px;width:420px;border:1px solid var(--gris3);}
  .modal h3{font-size:1rem;font-weight:700;margin-bottom:6px;}
  .modal p{font-size:0.82rem;color:#888;margin-bottom:20px;}
  .modal input{width:100%;background:var(--gris2);border:1px solid var(--gris3);border-radius:10px;padding:12px 14px;color:var(--texte);font-family:'Space Grotesk',sans-serif;font-size:0.88rem;outline:none;margin-bottom:12px;}
  .modal input:focus{border-color:var(--vert);}
  .modal-actions{display:flex;gap:10px;margin-top:4px;}
  .modal-actions .btn-action{flex:1;padding:12px;text-align:center;}
  .modal-msg{font-size:0.78rem;margin-top:10px;text-align:center;}
  .modal-msg.ok{color:var(--vert);} .modal-msg.err{color:var(--rouge);}

  @media(max-width:900px){.sidebar{display:none;}.main{margin-left:0;padding:20px;}.kpi-grid{grid-template-columns:1fr 1fr;}}
</style>
</head>
<body>

<div class="sidebar">
  <div class="sidebar-logo">
    <div class="icon">💬</div>
    <div>
      <div class="name">Hope to Million</div>
      <div class="sub">Admin Panel</div>
    </div>
  </div>
  <a class="nav-item active" href="/admin/dashboard?token={{ token }}">▪ Boutiques</a>
  <a class="nav-item" href="/health">▪ Health Check</a>
  <div class="sidebar-footer">v3.2 · Green API<br>{{ now }}</div>
</div>

<div class="main">
  <div class="topbar">
    <h1>Dashboard Admin</h1>
    <div class="date">{{ now }}</div>
  </div>

  <div class="kpi-grid">
    <div class="kpi vert"><div class="label">Boutiques actives</div><div class="value">{{ stats.actives }}</div><div class="sub">abonnements en cours</div></div>
    <div class="kpi gold"><div class="label">Revenus MRR</div><div class="value">{{ "{:,}".format(stats.mrr) }}</div><div class="sub">FCFA / mois</div></div>
    <div class="kpi rouge"><div class="label">Expirées / Bloquées</div><div class="value">{{ stats.inactives }}</div><div class="sub">à relancer</div></div>
    <div class="kpi bleu"><div class="label">Total commandes</div><div class="value">{{ stats.commandes }}</div><div class="sub">depuis le début</div></div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>Toutes les boutiques</h2>
      <span class="badge-count">{{ boutiques|length }}</span>
    </div>
    {% if boutiques %}
    <table>
      <thead>
        <tr><th>Boutique</th><th>Statut</th><th>Instance</th><th>Expiration</th><th>Revenus</th><th>Actions</th></tr>
      </thead>
      <tbody>
        {% for b in boutiques %}
        <tr>
          <td>
            <div class="boutique-name">{{ b.nom_boutique }}</div>
            <div class="boutique-ville">📍 {{ b.ville }} · {{ b.whatsapp }}</div>
          </td>
          <td>
            <span class="statut-badge {{ b.statut }}">
              {% if b.statut == 'actif' %}✅ Actif{% elif b.statut == 'expire' %}⏰ Expiré{% else %}⛔ Bloqué{% endif %}
            </span>
          </td>
          <td>
            {% if b.has_instance %}
            <span class="instance-badge ok">✅ Configurée</span>
            {% else %}
            <span class="instance-badge missing">⚠️ Manquante</span>
            {% endif %}
          </td>
          <td>
            <span class="expiration {{ b.expiration_class }}">{{ b.date_expiration_fmt }}</span>
            <span class="jours-badge {{ b.expiration_class }}">{{ b.jours_restants }}j</span>
          </td>
          <td><span class="revenu">{{ "{:,}".format(b.revenus) }} F</span></td>
          <td>
            <div class="actions">
              <a class="btn-action voir" href="/dashboard/{{ b.id }}" target="_blank">Voir</a>
              <button class="btn-action config" onclick="ouvrirModal('{{ b.id }}', '{{ b.nom_boutique }}')">⚙️ Instance</button>
              {% if b.statut != 'bloque' %}
              <a class="btn-action bloquer" href="/admin/boutique/{{ b.id }}/bloquer?token={{ token }}">Bloquer</a>
              {% else %}
              <a class="btn-action activer" href="/admin/boutique/{{ b.id }}/activer?token={{ token }}">Activer</a>
              {% endif %}
            </div>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">Aucune boutique enregistrée pour l'instant.</div>
    {% endif %}
  </div>
</div>

<!-- Modal config instance -->
<div class="modal-overlay" id="modal">
  <div class="modal">
    <h3>⚙️ Configurer l'instance Green API</h3>
    <p id="modal-subtitle">Boutique : <strong id="modal-nom"></strong></p>
    <input type="text" id="modal-id-instance" placeholder="idInstance (ex: 1234567890)" />
    <input type="text" id="modal-token-instance" placeholder="apiTokenInstance" />
    <div class="modal-actions">
      <button class="btn-action voir" onclick="fermerModal()">Annuler</button>
      <button class="btn-action activer" onclick="sauvegarderInstance()">✅ Sauvegarder</button>
    </div>
    <div class="modal-msg" id="modal-msg"></div>
  </div>
</div>

<script>
  const ADMIN_TOKEN = "{{ token }}";
  let currentBoutiqueId = null;

  function ouvrirModal(boutiqueId, nom) {
    currentBoutiqueId = boutiqueId;
    document.getElementById('modal-nom').textContent = nom;
    document.getElementById('modal-id-instance').value = '';
    document.getElementById('modal-token-instance').value = '';
    document.getElementById('modal-msg').textContent = '';
    document.getElementById('modal').classList.add('open');
  }

  function fermerModal() {
    document.getElementById('modal').classList.remove('open');
  }

  async function sauvegarderInstance() {
    const idInstance        = document.getElementById('modal-id-instance').value.trim();
    const apiTokenInstance  = document.getElementById('modal-token-instance').value.trim();
    const msgEl             = document.getElementById('modal-msg');

    if (!idInstance || !apiTokenInstance) {
      msgEl.textContent = '❌ Les deux champs sont requis';
      msgEl.className = 'modal-msg err';
      return;
    }

    try {
      const res = await fetch(`/admin/boutique/${currentBoutiqueId}/set-instance?token=${ADMIN_TOKEN}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({idInstance, apiTokenInstance})
      });
      const data = await res.json();
      if (data.status === 'ok') {
        msgEl.textContent = '✅ Instance configurée ! Rechargement...';
        msgEl.className = 'modal-msg ok';
        setTimeout(() => location.reload(), 1500);
      } else {
        msgEl.textContent = '❌ ' + (data.message || 'Erreur');
        msgEl.className = 'modal-msg err';
      }
    } catch(e) {
      msgEl.textContent = '❌ Erreur réseau';
      msgEl.className = 'modal-msg err';
    }
  }

  document.getElementById('modal').addEventListener('click', function(e) {
    if (e.target === this) fermerModal();
  });
</script>
</body>
</html>
"""

@app.route("/admin/dashboard")
def admin_dashboard():
    token = request.args.get("token", "")
    if token != ADMIN_TOKEN:
        return "Accès refusé", 403

    db = load_db()
    boutiques_data = []

    for bid, b in db["boutiques"].items():
        commandes_b = [c for c in db["commandes"] if c.get("boutique_id") == bid]
        revenus_b   = sum(c["montant"] for c in commandes_b if c.get("statut") == "ACCEPTED")
        jours       = jours_restants(b)
        exp_class   = "urgent" if jours <= 3 else ("warning" if jours <= 7 else "ok")
        exp_fmt     = ""
        if b.get("date_expiration"):
            try:
                exp_fmt = datetime.fromisoformat(b["date_expiration"]).strftime("%d/%m/%Y")
            except:
                exp_fmt = b.get("date_expiration", "")[:10]

        boutiques_data.append({
            "id": bid,
            "nom_boutique": b.get("nom_boutique", ""),
            "ville": b.get("ville", ""),
            "whatsapp": b.get("whatsapp", ""),
            "statut": b.get("statut", ""),
            "has_instance": bool(b.get("id_instance")),
            "date_expiration_fmt": exp_fmt,
            "jours_restants": jours,
            "expiration_class": exp_class,
            "nb_commandes": len(commandes_b),
            "revenus": revenus_b,
        })

    boutiques_data.sort(key=lambda x: x["jours_restants"])
    actives   = sum(1 for b in boutiques_data if b["statut"] == "actif")
    inactives = sum(1 for b in boutiques_data if b["statut"] in ["expire", "bloque"])

    class BoutiqueObj:
        def __init__(self, d): self.__dict__.update(d)

    return render_template_string(
        ADMIN_DASHBOARD_HTML,
        boutiques=[BoutiqueObj(b) for b in boutiques_data],
        stats=type('S', (), {"actives": actives, "inactives": inactives, "mrr": actives * PRIX_ABONNEMENT, "commandes": len(db["commandes"])})(),
        token=token,
        now=datetime.now().strftime("%d/%m/%Y %H:%M")
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
