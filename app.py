"""
=====================================
  WhatsApp CRM SaaS - Version 2.0
  Multi-boutiques | Dashboard | Admin
=====================================
"""

import os
import json
import requests
from flask import Flask, request, jsonify, render_template_string, redirect, session
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
# PROMPT PAR DÉFAUT
# =============================================
PROMPT_DEFAULT = """
Tu es Amina, une assistante commerciale virtuelle au Burkina Faso.
Tu réponds en français chaleureux style Afrique de l'Ouest.
Tu accueilles le client, identifies son besoin, présentes les produits et gères les objections.
Quand le client est prêt à payer, collecte: NOM, NUMÉRO MOBILE MONEY, MONTANT.
Quand tu as ces 3 infos, termine avec: [PRET_PAIEMENT:nom|numero|montant]
"""

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
    print(f"[MESSAGE] {from_number}: {message_body}")

    db = load_db()

    # Créer profil client si nouveau
    if from_number not in db["clients"]:
        db["clients"][from_number] = {
            "numero": from_number,
            "historique": [],
            "premiere_contact": datetime.now().isoformat()
        }

    client_data = db["clients"][from_number]
    client_data["historique"].append({"role": "user", "content": message_body})
    historique_recent = client_data["historique"][-10:]

    # Trouver la boutique du client
    boutique_id = from_number.replace("whatsapp:+", "")
    boutique = db.get("boutiques", {}).get(boutique_id)

    if boutique:
        prompt = f"""
Tu es Amina, assistante de {boutique['nom_boutique']} à {boutique['ville']}.
Produits: {boutique['produits']}
{boutique.get('message_perso', '')}
Tu réponds en français chaleureux.
Quand le client veut payer, collecte NOM, NUMÉRO MOBILE MONEY, MONTANT.
Termine avec: [PRET_PAIEMENT:nom|numero|montant]
"""
    else:
        prompt = PROMPT_DEFAULT

    reponse_ia = ask_groq(historique_recent, prompt)
    reponse_finale = reponse_ia

    # Détection paiement
    if "[PRET_PAIEMENT:" in reponse_ia:
        try:
            debut = reponse_ia.index("[PRET_PAIEMENT:") + len("[PRET_PAIEMENT:")
            fin = reponse_ia.index("]", debut)
            infos = reponse_ia[debut:fin].split("|")
            nom, numero, montant_str = infos[0], infos[1], infos[2]
            montant = int(montant_str.replace("FCFA","").replace("fcfa","").replace(" ",""))

            transaction_id = f"CMD_{int(datetime.now().timestamp())}"

            paiement = creer_lien_paiement(transaction_id, montant, nom, numero)

            db["commandes"].append({
                "transaction_id": transaction_id,
                "client": from_number,
                "boutique_id": boutique_id,
                "nom": nom,
                "numero_mobile_money": numero,
                "montant": montant,
                "statut": "EN_ATTENTE",
                "date": datetime.now().isoformat()
            })

            texte = reponse_ia.split("[PRET_PAIEMENT:")[0].strip()
            if paiement["success"]:
                reponse_finale = f"{texte}\n\n✅ Commande créée !\n👤 {nom}\n💰 {montant:,} FCFA\n\n🔗 Paye ici:\n{paiement['lien']}\n\nMerci 🙏"
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
                f"🎉 Paiement confirmé ! Merci {commande['nom']} 🙏\nMontant: {commande['montant']:,} FCFA ✅"
            )
            break

    save_db(db)
    return jsonify({"status": "ok"})

# =============================================
# ONBOARDING - SOUMETTRE BOUTIQUE
# =============================================
@app.route("/submit-onboarding", methods=["POST"])
def submit_onboarding():
    data = request.json
    db = load_db()

    boutique_id = data.get('whatsapp', '').replace('+', '').replace(' ', '')

    db["boutiques"][boutique_id] = {
        "nom_boutique": data.get('nom_boutique'),
        "ville": data.get('ville'),
        "produits": data.get('produits'),
        "orange_money": data.get('orange_money'),
        "email": data.get('email'),
        "tarif": data.get('tarif'),
        "message_perso": data.get('message_perso', ''),
        "whatsapp": data.get('whatsapp'),
        "date_inscription": datetime.now().isoformat(),
        "statut": "actif"
    }
    save_db(db)

    # Notifier le propriétaire
    envoyer_whatsapp(
        MON_NUMERO,
        f"🆕 Nouvelle boutique !\n\n"
        f"🏪 {data.get('nom_boutique')}\n"
        f"📍 {data.get('ville')}\n"
        f"📱 {data.get('whatsapp')}\n"
        f"💰 Orange Money: {data.get('orange_money')}\n"
        f"🛍️ Produits: {data.get('produits')}\n"
        f"💎 Formule: {data.get('tarif')}"
    )

    return jsonify({
        "status": "ok",
        "boutique_id": boutique_id,
        "dashboard_url": f"/dashboard/{boutique_id}",
        "numero_whatsapp": "+14155238886"
    })

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
  :root { --vert:#25D366; --noir:#0D0D0D; --gris:#1A1A1A; --gris2:#2A2A2A; --texte:#F0F0F0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--noir); color:var(--texte); font-family:'Plus Jakarta Sans',sans-serif; padding:20px; }
  .header { text-align:center; padding:24px 0 32px; }
  .logo { width:56px;height:56px;background:var(--vert);border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:28px;margin:0 auto 12px; }
  h1 { font-size:1.5rem;font-weight:800; }
  h1 span { color:var(--vert); }
  .badge { display:inline-block;background:rgba(37,211,102,.15);color:var(--vert);border:1px solid rgba(37,211,102,.3);padding:4px 12px;border-radius:100px;font-size:0.75rem;margin-top:8px; }
  .stats { display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:20px 0; }
  .stat { background:var(--gris);border-radius:16px;padding:20px;border:1px solid var(--gris2); }
  .stat .label { font-size:0.72rem;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px; }
  .stat .value { font-size:1.8rem;font-weight:800; }
  .stat.vert .value { color:var(--vert); }
  .numero-card { background:var(--gris);border-radius:16px;padding:20px;border:2px solid var(--vert);margin-bottom:20px;text-align:center; }
  .numero-card .label { font-size:0.8rem;color:#888;margin-bottom:8px; }
  .numero-card .numero { font-size:1.4rem;font-weight:800;color:var(--vert);letter-spacing:0.05em; }
  .numero-card .hint { font-size:0.75rem;color:#666;margin-top:8px; }
  .commandes-title { font-size:0.8rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#888;margin:20px 0 12px; }
  .commande { background:var(--gris);border-radius:12px;padding:16px;margin-bottom:10px;border:1px solid var(--gris2);display:flex;justify-content:space-between;align-items:center; }
  .commande .info { font-size:0.88rem; }
  .commande .info .nom { font-weight:700; }
  .commande .info .date { color:#666;font-size:0.75rem;margin-top:2px; }
  .commande .montant { font-weight:800;color:var(--vert); }
  .tag { display:inline-block;padding:3px 10px;border-radius:100px;font-size:0.7rem;font-weight:600; }
  .tag.ok { background:rgba(37,211,102,.15);color:var(--vert); }
  .tag.wait { background:rgba(255,214,0,.15);color:#FFD600; }
  .empty { text-align:center;padding:40px;color:#555; }
  .btn-refresh { width:100%;background:var(--vert);color:#000;border:none;border-radius:12px;padding:14px;font-family:'Plus Jakarta Sans',sans-serif;font-size:0.9rem;font-weight:700;cursor:pointer;margin-top:16px; }
</style>
</head>
<body>
<div class="header">
  <div class="logo">💬</div>
  <h1>{{ boutique.nom_boutique }}</h1>
  <span class="badge">● EN LIGNE</span>
</div>

<div class="numero-card">
  <div class="label">Votre numéro WhatsApp Bot</div>
  <div class="numero">+1 415 523 8886</div>
  <div class="hint">Partagez ce numéro à vos clients 👆</div>
</div>

<div class="stats">
  <div class="stat">
    <div class="label">Commandes</div>
    <div class="value">{{ total_commandes }}</div>
  </div>
  <div class="stat vert">
    <div class="label">Revenus</div>
    <div class="value">{{ revenus }}</div>
  </div>
  <div class="stat">
    <div class="label">Payées</div>
    <div class="value">{{ payees }}</div>
  </div>
  <div class="stat">
    <div class="label">En attente</div>
    <div class="value">{{ en_attente }}</div>
  </div>
</div>

<div class="commandes-title">Commandes récentes</div>

{% if commandes %}
  {% for c in commandes|reverse %}
  <div class="commande">
    <div class="info">
      <div class="nom">{{ c.nom }}</div>
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
        return "Boutique introuvable", 404

    commandes = [c for c in db["commandes"] if c.get("boutique_id") == boutique_id]
    payees = sum(1 for c in commandes if c["statut"] == "ACCEPTED")
    en_attente = sum(1 for c in commandes if c["statut"] == "EN_ATTENTE")
    revenus = sum(c["montant"] for c in commandes if c["statut"] == "ACCEPTED")

    from flask import render_template_string
    return render_template_string(
        DASHBOARD_CLIENT_HTML,
        boutique=boutique,
        commandes=commandes,
        total_commandes=len(commandes),
        payees=payees,
        en_attente=en_attente,
        revenus=f"{revenus:,} FCFA"
    )

# =============================================
# DASHBOARD ADMIN (TOI)
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
  :root { --vert:#25D366; --noir:#0D0D0D; --gris:#1A1A1A; --gris2:#2A2A2A; --texte:#F0F0F0; --accent:#FFD700; }
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
  .stat.gold .value { color:var(--accent); }
  .section-title { font-size:0.8rem;font-weight:700;text-transform:uppercase;color:#888;margin:20px 0 12px; }
  .boutique-card { background:var(--gris);border-radius:16px;padding:16px;margin-bottom:12px;border:1px solid var(--gris2); }
  .boutique-card .nom { font-size:1rem;font-weight:700; }
  .boutique-card .info { font-size:0.78rem;color:#888;margin-top:4px; }
  .boutique-card .stats-inline { display:flex;gap:16px;margin-top:12px; }
  .boutique-card .stat-inline { font-size:0.8rem; }
  .boutique-card .stat-inline span { color:var(--vert);font-weight:700; }
  .btn-view { display:inline-block;margin-top:10px;padding:6px 14px;background:rgba(37,211,102,.15);color:var(--vert);border:1px solid rgba(37,211,102,.3);border-radius:100px;font-size:0.75rem;text-decoration:none; }
  .btn-refresh { width:100%;background:var(--vert);color:#000;border:none;border-radius:12px;padding:14px;font-family:'Plus Jakarta Sans',sans-serif;font-size:0.9rem;font-weight:700;cursor:pointer;margin-top:16px; }
</style>
</head>
<body>
<div class="header">
  <h1>Admin <span>CRM</span></h1>
  <p style="color:#666;font-size:0.85rem;margin-top:4px;">Tableau de bord propriétaire</p>
</div>

<div class="stats">
  <div class="stat">
    <div class="label">Boutiques</div>
    <div class="value">{{ total_boutiques }}</div>
  </div>
  <div class="stat vert">
    <div class="label">Commandes</div>
    <div class="value">{{ total_commandes }}</div>
  </div>
  <div class="stat gold">
    <div class="label">Revenus clients</div>
    <div class="value" style="font-size:1.2rem">{{ revenus_total }}</div>
  </div>
  <div class="stat">
    <div class="label">Payées</div>
    <div class="value">{{ total_payees }}</div>
  </div>
</div>

<div class="section-title">Mes boutiques</div>

{% for id, b in boutiques.items() %}
<div class="boutique-card">
  <div class="nom">{{ b.nom_boutique }}</div>
  <div class="info">📍 {{ b.ville }} · 📱 {{ b.whatsapp }}</div>
  <div class="stats-inline">
    <div class="stat-inline">Commandes: <span>{{ b.nb_commandes }}</span></div>
    <div class="stat-inline">Revenus: <span>{{ b.revenus }} F</span></div>
  </div>
  <a class="btn-view" href="/dashboard/{{ id }}">Voir dashboard →</a>
</div>
{% endfor %}

<button class="btn-refresh" onclick="location.reload()">↻ Actualiser</button>
</body>
</html>
"""

@app.route("/admin")
def admin():
    token = request.args.get("token", "")
    if token != ADMIN_TOKEN:
        return "⛔ Accès refusé", 403

    db = load_db()
    boutiques = db.get("boutiques", {})
    commandes = db.get("commandes", [])

    # Stats par boutique
    boutiques_avec_stats = {}
    for bid, b in boutiques.items():
        cmds = [c for c in commandes if c.get("boutique_id") == bid]
        revenus = sum(c["montant"] for c in cmds if c["statut"] == "ACCEPTED")
        boutiques_avec_stats[bid] = {**b, "nb_commandes": len(cmds), "revenus": f"{revenus:,}"}

    total_payees = sum(1 for c in commandes if c["statut"] == "ACCEPTED")
    revenus_total = sum(c["montant"] for c in commandes if c["statut"] == "ACCEPTED")

    from flask import render_template_string
    return render_template_string()
        ADMIN_HTML,
        boutiques=boutiques_avec_stats,
        total_boutiques=len(boutiques),
        total_commandes=len
