cat > /home/claude/app.py << 'PYEOF'
"""
=====================================
  WhatsApp CRM SaaS - Version 3.1
  Multi-boutiques | Admin | Abonnement
  Blocage | Notifications | Production
  Green API (WhatsApp personnel)
=====================================
"""

import os
import json
import re
import requests
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "whatsapp-crm-secret-2024")

# =============================================
# CONFIG
# =============================================
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
CINETPAY_API_KEY = os.getenv("CINETPAY_API_KEY")
CINETPAY_SITE_ID = os.getenv("CINETPAY_SITE_ID")

# Green API - compte admin pour les notifications
GREEN_API_ID_INSTANCE    = os.getenv("GREEN_API_ID_INSTANCE")
GREEN_API_TOKEN_INSTANCE = os.getenv("GREEN_API_TOKEN_INSTANCE")

# Green API partenaire (pour créer des instances automatiquement)
GREEN_API_PARTNER_TOKEN  = os.getenv("GREEN_API_PARTNER_TOKEN")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin123")
MON_NUMERO  = os.getenv("MON_NUMERO", "22675000000")  # Sans + ni espaces
APP_URL     = os.getenv("APP_URL", "https://whatsapp-crm-s4io.onrender.com")

PRIX_ABONNEMENT         = 50000
DUREE_ABONNEMENT_JOURS  = 30

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
    """Convertit +22670000000 → 22670000000@c.us"""
    propre = re.sub(r'[^\d]', '', numero)
    return f"{propre}@c.us"

# =============================================
# GREEN API - ENVOI MESSAGES
# =============================================
def envoyer_whatsapp(numero_dest, message, id_instance=None, token_instance=None):
    """
    Envoie un message WhatsApp via Green API.
    Utilise les credentials du compte admin par défaut,
    ou les credentials spécifiques d'une boutique.
    """
    iid   = id_instance    or GREEN_API_ID_INSTANCE
    token = token_instance or GREEN_API_TOKEN_INSTANCE

    if not iid or not token:
        print(f"[GREEN API] Credentials manquants pour envoyer à {numero_dest}")
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
# GREEN API - CRÉER UNE INSTANCE (par boutique)
# =============================================
def creer_instance_green_api():
    """
    Crée une nouvelle instance Green API pour un user.
    Nécessite un compte partenaire Green API.
    Retourne {idInstance, apiTokenInstance} ou None.
    """
    if not GREEN_API_PARTNER_TOKEN:
        print("[GREEN API] Pas de partner token configuré")
        return None

    url = "https://api.green-api.com/partner/createInstance/accountId"
    # Remplace 'accountId' par ton ID de compte partenaire Green API

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
        print(f"[GREEN API] Erreur création instance: {data}")
        return None
    except Exception as e:
        print(f"[ERREUR GREEN API] Création instance: {e}")
        return None

# =============================================
# GREEN API - WEBHOOK ENTRANT
# =============================================
@app.route("/webhook/green-api/<boutique_id>", methods=["POST"])
def webhook_green_api(boutique_id):
    """
    Reçoit les messages WhatsApp entrants via Green API.
    Chaque boutique a son propre endpoint webhook.
    """
    data = request.json or {}
    type_notif = data.get("typeWebhook", "")

    if type_notif != "incomingMessageReceived":
        return jsonify({"status": "ok"})

    sender_data = data.get("senderData", {})
    from_number = sender_data.get("sender", "").replace("@c.us", "")
    if not from_number.startswith("+"):
        from_number = "+" + from_number

    message_data = data.get("messageData", {})
    message_body = sanitize(
        message_data.get("textMessageData", {}).get("textMessage", "").strip()
    )

    if not message_body:
        return jsonify({"status": "ok"})

    print(f"[MESSAGE] boutique={boutique_id} from={from_number}: {message_body}")

    db = load_db()

    client_key = f"{boutique_id}_{from_number}"
    if client_key not in db["clients"]:
        db["clients"][client_key] = {
            "numero": from_number,
            "boutique_id": boutique_id,
            "historique": [],
            "premiere_contact": datetime.now().isoformat()
        }

    client_data = db["clients"][client_key]
    client_data["historique"].append({"role": "user", "content": message_body})
    historique_recent = client_data["historique"][-10:]

    boutique = db.get("boutiques", {}).get(boutique_id)

    if boutique:
        active, raison = boutique_active(boutique)
        if not active:
            if raison == "bloque":
                msg = "⛔ Ce service est temporairement suspendu. Contactez le propriétaire."
            else:
                msg = "⏰ L'abonnement de cette boutique a expiré. Contactez le propriétaire pour le renouvellement."
            envoyer_whatsapp(
                from_number, msg,
                boutique.get("id_instance"),
                boutique.get("api_token_instance")
            )
            return jsonify({"status": "ok"})

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

    # Envoyer la réponse via l'instance de la boutique
    envoyer_whatsapp(
        from_number,
        reponse_finale,
        boutique.get("id_instance") if boutique else None,
        boutique.get("api_token_instance") if boutique else None
    )

    client_data["historique"].append({"role": "assistant", "content": reponse_finale})
    client_data["derniere_activite"] = datetime.now().isoformat()
    save_db(db)

    return jsonify({"status": "ok"})

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
                f"⚠️ *Rappel abonnement*\n\n"
                f"Bonjour {boutique['nom_boutique']} !\n"
                f"Votre abonnement Amina expire dans *3 jours*.\n"
                f"Renouvelez maintenant pour continuer à recevoir des commandes.\n\n"
                f"💰 Renouvellement: *{PRIX_ABONNEMENT:,} FCFA/mois*\n"
                f"📱 Contactez-nous pour renouveler.",
                iid, token
            )
            envoyer_whatsapp(
                MON_NUMERO,
                f"⚠️ Boutique {boutique['nom_boutique']} expire dans 3 jours !"
            )

        if jours == 0 and boutique.get("statut") == "actif":
            db["boutiques"][bid]["statut"] = "expire"
            envoyer_whatsapp(
                whatsapp,
                f"🔴 *Abonnement expiré*\n\n"
                f"Bonjour {boutique['nom_boutique']} !\n"
                f"Votre abonnement Amina a expiré.\n"
                f"Amina ne répond plus à vos clients.\n\n"
                f"Renouvelez maintenant: *{PRIX_ABONNEMENT:,} FCFA/mois*",
                iid, token
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
            headers=headers, json=payload, timeout=20
        )
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
                f"🎉 *Paiement confirmé !*\n\n"
                f"Merci {commande['nom']} 🙏\n"
                f"🛍️ {commande.get('produit', 'Votre commande')}\n"
                f"💰 {commande['montant']:,} FCFA ✅\n\n"
                f"📦 Livraison à: {commande.get('adresse', 'En cours')}\n"
                f"Nous vous contacterons bientôt.",
                boutique.get("id_instance"),
                boutique.get("api_token_instance")
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
    date_expiration  = date_inscription + timedelta(days=DUREE_ABONNEMENT_JOURS)

    # Créer une instance Green API pour cette boutique
    instance = creer_instance_green_api()
    id_instance       = instance["idInstance"]       if instance else None
    api_token_instance = instance["apiTokenInstance"] if instance else None

    # Configurer le webhook de l'instance vers notre serveur
    if id_instance and api_token_instance:
        try:
            webhook_url = f"{APP_URL}/webhook/green-api/{boutique_id}"
            requests.post(
                f"https://api.green-api.com/waInstance{id_instance}/setSettings/{api_token_instance}",
                json={
                    "incomingWebhook": "yes",
                    "webhookUrl": webhook_url
                },
                timeout=10
            )
            print(f"[GREEN API] Webhook configuré: {webhook_url}")
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
        f"🆕 *Nouvelle boutique !*\n\n"
        f"🏪 {data.get('nom_boutique')}\n"
        f"📍 {data.get('ville')}\n"
        f"📱 {whatsapp}\n"
        f"💰 Mobile Money: {orange}\n"
        f"🛍️ {data.get('produits')}\n"
        f"📅 Expire le: {date_expiration.strftime('%d/%m/%Y')}\n"
        f"✅ PAIEMENT CONFIRMÉ - {PRIX_ABONNEMENT:,} FCFA/mois"
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
        b = db["boutiques"][boutique_id]
        envoyer_whatsapp(
            b.get("whatsapp", ""),
            f"⛔ Votre boutique {b['nom_boutique']} a été suspendue.\nContactez le support.",
            b.get("id_instance"), b.get("api_token_instance")
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
        date_expiration = datetime.now() + timedelta(days=DUREE_ABONNEMENT_JOURS)
        db["boutiques"][boutique_id]["statut"] = "actif"
        db["boutiques"][boutique_id]["date_expiration"] = date_expiration.isoformat()
        save_db(db)
        b = db["boutiques"][boutique_id]
        envoyer_whatsapp(
            b.get("whatsapp", ""),
            f"✅ Votre boutique {b['nom_boutique']} est maintenant active !\n"
            f"Abonnement valide jusqu'au {date_expiration.strftime('%d/%m/%Y')} 🎉",
            b.get("id_instance"), b.get("api_token_instance")
        )
        return jsonify({"status": "ok", "message": "Boutique activée"})
    return jsonify({"status": "error"}), 404

# =============================================
# DASHBOARD CLIENT (inchangé)
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
  .stats { display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0; }
  .stat { background:var(--gris);border-radius:16px;padding:20px;border:1px solid var(--gris2); }
  .stat .label { font-size:0.72rem;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px; }
  .stat .value { font-size:1.8rem;font-weight:800; }
  .stat.vert .value { color:var(--vert); }
  .stat.gold .value { color:var(--gold); }
  .section-title { font-size:0.8rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#888;margin:20px 0 12px; }
  .commande { background:var(--gris);border-radius:12px;padding:16px;margin-bottom:10px;border:1px solid var(--gris2); }
  .commande .top { display:flex;justify-content:space-between;align-items:flex-start; }
  .commande .nom { font-weight:700;font-size:0.95rem; }
  .commande .montant { color:var(--vert);font-weight:800; }
  .commande .detail { font-size:0.8rem;color:#888;margin-top:6px; }
  .badge-statut { font-size:0.7rem;padding:3px 8px;border-radius:100px; }
  .badge-statut.accepted { background:rgba(37,211,102,.15);color:var(--vert); }
  .badge-statut.en_attente { background:rgba(255,214,0,.15);color:var(--gold); }
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
    <div class="label">Revenus</div>
    <div class="value">{{ "{:,}".format(total_revenus) }}</div>
  </div>
</div>

<div class="section-title">Dernières commandes</div>
{% for cmd in commandes[-10:]|reverse %}
<div class="commande">
  <div class="top">
    <div class="nom">{{ cmd.nom }}</div>
    <div class="montant">{{ "{:,}".format(cmd.montant) }} F</div>
  </div>
  <div class="detail">🛍️ {{ cmd.produit }} · 📍 {{ cmd.adresse }}</div>
  <div class="detail" style="margin-top:4px">
    <span class="badge-statut {{ cmd.statut.lower() }}">{{ cmd.statut }}</span>
    · {{ cmd.date[:10] }}
  </div>
</div>
{% else %}
<p style="color:#555;text-align:center;padding:20px">Aucune commande pour l'instant</p>
{% endfor %}
</body>
</html>
"""

@app.route("/dashboard/<boutique_id>")
def dashboard(boutique_id):
    db = load_db()
    boutique = db["boutiques"].get(boutique_id)
    if not boutique:
        return "Boutique introuvable", 404
    commandes = [c for c in db["commandes"] if c.get("boutique_id") == boutique_id]
    total_revenus = sum(c["montant"] for c in commandes if c.get("statut") == "ACCEPTED")
    return render_template_string(
        DASHBOARD_CLIENT_HTML,
        boutique=type('B', (), boutique)(),
        commandes=commandes,
        total_revenus=total_revenus
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
PYEOF
echo "Done"
