"""
=====================================
  WhatsApp CRM Lite - MVP Complet
  Pour: Commerces Burkina Faso
  Stack: Flask + Twilio + Groq AI + CinetPay
=====================================
"""

import os
import json
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.getenv("SESSION_SECRET") or os.getenv("SECRET_KEY", "fallback-secret-key")

# =============================================
# CONFIGURATION - METS TES VRAIES CLÉS ICI
# =============================================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"  # Numéro sandbox Twilio

GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "gsk_xxxx")

CINETPAY_API_KEY   = os.getenv("CINETPAY_API_KEY",  "TA_CLE_CINETPAY")
CINETPAY_SITE_ID   = os.getenv("CINETPAY_SITE_ID",  "TON_SITE_ID")

# =============================================
# BASE DE DONNÉES SIMPLE (fichier JSON)
# En production, remplace par PostgreSQL
# =============================================
DB_FILE = "crm_data.json"

def load_db():
    """Charge la base de données depuis le fichier JSON"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"clients": {}, "commandes": []}

def save_db(data):
    """Sauvegarde la base de données"""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =============================================
# MODULE IA - GROQ POUR QUALIFIER LES CLIENTS
# =============================================
# Charger les infos de la boutique si disponibles
boutique_id = from_number.replace("whatsapp:+", "").replace(" ", "")
db_temp = load_db()
boutique = db_temp.get("boutiques", {}).get(boutique_id)

if boutique:
    prompt = f"""
Tu es Amina, assistante commerciale de {boutique['nom']} à {boutique['ville']}, Burkina Faso.
Tu réponds en français chaleureux style Afrique de l'Ouest.
Produits disponibles: {boutique['produits']}
Livraison gratuite au-dessus de 20 000 FCFA, sinon 2 000 FCFA.
{boutique.get('message_perso', '')}
Quand le client veut payer, collecte NOM, NUMÉRO MOBILE MONEY, MONTANT.
Termine avec: [PRET_PAIEMENT:nom|numero|montant]
"""
else:
    prompt = SYSTEM_PROMPT


# Appel à Groq
reponse_ia = ask_groq(historique_recent, prompt)

# === Configuration de l'appel API ===
headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

messages = [{"role": "system", "content": system_prompt}] + conversation_history

payload = {
    "model": "llama-3.3-70b-versatile",
    "max_tokens": 500,
    "messages": messages
}
try:
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
except Exception as e:
    print(f"[ERREUR IA] {e}")
    return "Désolé, je rencontre un problème technique. Réessaie dans un instant 🙏"
        return "Désolé, je rencontre un problème technique. Réessaie dans un instant 🙏"

# Prompt système pour le bot commercial
SYSTEM_PROMPT = """
Tu es Amina, une assistante commerciale virtuelle d'une boutique en ligne au Burkina Faso.
Tu réponds uniquement en français simple et chaleureux, style Afrique de l'Ouest.
Ton rôle:
1. Accueillir chaleureusement le client
2. Identifier son besoin (quel produit/service il cherche)
3. Présenter les offres disponibles de façon claire
4. Gérer les objections (prix, délai, qualité) avec des arguments concrets
5. Quand le client est prêt à payer, lui demander: son nom complet, son numéro Orange Money ou Moov Money, et le montant à payer
6. Confirmer la commande et générer un lien de paiement

Produits disponibles:
- Téléphones reconditionnés: 35 000 à 120 000 FCFA
- Accessoires téléphones: 2 000 à 15 000 FCFA  
- Livraison Ouagadougou: gratuite au-dessus de 20 000 FCFA, sinon 2 000 FCFA

Sois concise (max 3-4 phrases par message), utilise des emojis avec modération.
Si le client veut payer, collecte obligatoirement: NOM, NUMÉRO MOBILE MONEY, MONTANT.
Quand tu as ces 3 infos, termine ton message avec exactement: [PRET_PAIEMENT:nom|numero|montant]
"""

# =============================================
# MODULE PAIEMENT - CINETPAY
# =============================================
def creer_lien_paiement(transaction_id: str, montant: int, nom_client: str, tel_client: str) -> dict:
    """
    Crée un lien de paiement Mobile Money via CinetPay.
    Supporte Orange Money et Moov Money au Burkina Faso.
    """
    payload = {
        "apikey": CINETPAY_API_KEY,
        "site_id": CINETPAY_SITE_ID,
        "transaction_id": transaction_id,
        "amount": montant,
        "currency": "XOF",
        "description": f"Commande WhatsApp - {nom_client}",
        "return_url": "https://ton-site.com/merci",
        "notify_url": "https://ton-site.com/webhook/paiement",  # Change avec ton URL ngrok
        "customer_name": nom_client,
        "customer_phone_number": tel_client,
        "channels": "MOBILE_MONEY",
        "lang": "fr",
        "metadata": json.dumps({"source": "whatsapp_crm"})
    }
    try:
        resp = requests.post(
            "https://api-checkout.cinetpay.com/v2/payment",
            json=payload,
            timeout=15
        )
        data = resp.json()
        if data.get("code") == "201":
            return {
                "success": True,
                "lien": data["data"]["payment_url"],
                "transaction_id": transaction_id
            }
        else:
            return {"success": False, "erreur": data.get("message", "Erreur inconnue")}
    except Exception as e:
        return {"success": False, "erreur": str(e)}

def verifier_paiement(transaction_id: str) -> dict:
    """Vérifie le statut d'un paiement CinetPay"""
    payload = {
        "apikey": CINETPAY_API_KEY,
        "site_id": CINETPAY_SITE_ID,
        "transaction_id": transaction_id
    }
    try:
        resp = requests.post(
            "https://api-checkout.cinetpay.com/v2/payment/check",
            json=payload,
            timeout=15
        )
        data = resp.json()
        return {
            "statut": data.get("data", {}).get("status", "UNKNOWN"),
            "montant": data.get("data", {}).get("amount", 0),
            "raw": data
        }
    except Exception as e:
        return {"statut": "ERREUR", "erreur": str(e)}

# =============================================
# WEBHOOK WHATSAPP (TWILIO)
# =============================================
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook/whatsapp", methods=["POST"])
def webhook_whatsapp():
    """
    Point d'entrée des messages WhatsApp entrants via Twilio.
    Twilio envoie les messages ici automatiquement.
    """
    # Récupération du message client
    from_number = request.form.get("From", "")  # Ex: whatsapp:+22670123456
    message_body = request.form.get("Body", "").strip()
    
    print(f"[MESSAGE REÇU] De: {from_number} | Texte: {message_body}")
    
    # Chargement de la DB
    db = load_db()
    
    # Création du profil client si nouveau
    if from_number not in db["clients"]:
        db["clients"][from_number] = {
            "numero": from_number,
            "historique": [],
            "statut": "nouveau",
            "premiere_contact": datetime.now().isoformat()
        }
    
    client_data = db["clients"][from_number]
    
    # Ajout du message client à l'historique
    client_data["historique"].append({
        "role": "user",
        "content": message_body
    })
    
    # Garde uniquement les 10 derniers messages (économie de tokens)
    historique_recent = client_data["historique"][-10:]
    
    # Appel à Groq pour générer la réponse
    reponse_ia = ask_groq(historique_recent, SYSTEM_PROMPT)
    
    # Vérification si l'IA a collecté toutes les infos de paiement
    reponse_finale = reponse_ia
    if "[PRET_PAIEMENT:" in reponse_ia:
        # Extraction des données de paiement
        try:
            tag_debut = reponse_ia.index("[PRET_PAIEMENT:") + len("[PRET_PAIEMENT:")
            tag_fin = reponse_ia.index("]", tag_debut)
            infos = reponse_ia[tag_debut:tag_fin].split("|")
            nom, numero, montant_str = infos[0], infos[1], infos[2]
            montant = int(montant_str.replace(" ", "").replace("FCFA", "").replace("fcfa", ""))
            
            # Création d'un ID unique pour la transaction
            transaction_id = f"CMD_{from_number[-8:]}_{int(datetime.now().timestamp())}"
            
            # Génération du lien de paiement CinetPay
            paiement = creer_lien_paiement(transaction_id, montant, nom, numero)
            
            # Enregistrement de la commande
            db["commandes"].append({
                "transaction_id": transaction_id,
                "client": from_number,
                "nom": nom,
                "numero_mobile_money": numero,
                "montant": montant,
                "statut": "EN_ATTENTE",
                "date": datetime.now().isoformat()
            })
            
            # Construction du message final sans le tag technique
            reponse_propre = reponse_ia[:reponse_ia.index("[PRET_PAIEMENT:")].strip()
            
            if paiement["success"]:
                reponse_finale = (
                    f"{reponse_propre}\n\n"
                    f"✅ *Commande créée !*\n"
                    f"👤 {nom}\n"
                    f"💰 {montant:,} FCFA\n\n"
                    f"🔗 *Clique ici pour payer en toute sécurité:*\n"
                    f"{paiement['lien']}\n\n"
                    f"⏱️ Le lien expire dans 30 minutes. "
                    f"Tu recevras une confirmation dès le paiement validé ✓"
                )
            else:
                reponse_finale = (
                    f"{reponse_propre}\n\n"
                    f"⚠️ Problème technique pour générer le lien. "
                    f"Contacte-nous directement: *+226 XX XX XX XX*"
                )
        except Exception as e:
            print(f"[ERREUR PAIEMENT] {e}")
            reponse_finale = reponse_ia.split("[PRET_PAIEMENT:")[0].strip()
    
    # Ajout de la réponse à l'historique
    client_data["historique"].append({
        "role": "assistant",
        "content": reponse_finale
    })
    client_data["statut"] = "en_discussion"
    client_data["derniere_activite"] = datetime.now().isoformat()
    
    # Sauvegarde
    save_db(db)
    
    # Envoi de la réponse via Twilio
    resp = MessagingResponse()
    resp.message(reponse_finale)
    return str(resp)

# =============================================
# WEBHOOK PAIEMENT (CinetPay notify_url)
# =============================================
@app.route("/webhook/paiement", methods=["POST"])
def webhook_paiement():
    """
    CinetPay appelle cette URL quand un paiement est confirmé.
    Met à jour le statut de la commande et notifie le client WhatsApp.
    """
    data = request.json or request.form.to_dict()
    transaction_id = data.get("cpm_trans_id") or data.get("transaction_id")
    
    print(f"[WEBHOOK PAIEMENT] Transaction: {transaction_id}")
    
    if not transaction_id:
        return jsonify({"status": "error", "message": "transaction_id manquant"}), 400
    
    # Vérification du paiement auprès de CinetPay
    verification = verifier_paiement(transaction_id)
    
    db = load_db()
    
    # Mise à jour de la commande
    for commande in db["commandes"]:
        if commande["transaction_id"] == transaction_id:
            commande["statut"] = verification["statut"]
            commande["date_paiement"] = datetime.now().isoformat()
            
            # Notification WhatsApp au client
            if verification["statut"] == "ACCEPTED":
                envoyer_message_whatsapp(
                    commande["client"],
                    f"🎉 *Paiement confirmé !*\n\n"
                    f"Merci {commande['nom']} ! Ton paiement de "
                    f"*{commande['montant']:,} FCFA* a bien été reçu ✅\n\n"
                    f"📦 Ta commande est en cours de préparation.\n"
                    f"Nous te contactons dans les prochaines heures. Merci de ta confiance 🙏"
                )
            break
    
    save_db(db)
    return jsonify({"status": "ok"})

def envoyer_message_whatsapp(to_number: str, message: str):
    """Envoie un message WhatsApp sortant via Twilio"""
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to_number
        )
        print(f"[MESSAGE ENVOYÉ] À: {to_number}")
    except Exception as e:
        print(f"[ERREUR ENVOI] {e}")

# =============================================
# DASHBOARD - INTERFACE WEB SIMPLE
# =============================================
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WhatsApp CRM Lite - Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Space+Grotesk:wght@300;500;700&display=swap');
  
  :root {
    --vert: #00C853;
    --noir: #0A0A0A;
    --gris: #1A1A1A;
    --gris2: #2A2A2A;
    --texte: #E8E8E8;
    --accent: #FFD600;
  }
  
  * { margin:0; padding:0; box-sizing:border-box; }
  
  body {
    background: var(--noir);
    color: var(--texte);
    font-family: 'Space Grotesk', sans-serif;
    min-height: 100vh;
    padding: 24px;
  }
  
  header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 32px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--gris2);
  }
  
  .logo {
    width: 44px; height: 44px;
    background: var(--vert);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px;
  }
  
  h1 { font-size: 1.4rem; font-weight: 700; }
  h1 span { color: var(--vert); }
  
  .badge {
    margin-left: auto;
    background: var(--gris2);
    padding: 6px 14px;
    border-radius: 100px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    color: var(--vert);
    border: 1px solid #333;
  }
  
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }
  
  .stat-card {
    background: var(--gris);
    border-radius: 16px;
    padding: 20px;
    border: 1px solid var(--gris2);
  }
  
  .stat-card .label {
    font-size: 0.75rem;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 8px;
  }
  
  .stat-card .value {
    font-size: 2rem;
    font-weight: 700;
    font-family: 'IBM Plex Mono', monospace;
  }
  
  .stat-card.vert .value { color: var(--vert); }
  .stat-card.jaune .value { color: var(--accent); }
  .stat-card.blanc .value { color: #fff; }
  
  h2 {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 16px;
    color: #aaa;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  
  table {
    width: 100%;
    border-collapse: collapse;
    background: var(--gris);
    border-radius: 16px;
    overflow: hidden;
    font-size: 0.88rem;
  }
  
  th {
    text-align: left;
    padding: 14px 20px;
    background: var(--gris2);
    color: #888;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 500;
  }
  
  td {
    padding: 14px 20px;
    border-top: 1px solid var(--gris2);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
  }
  
  .tag {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 100px;
    font-size: 0.72rem;
    font-weight: 600;
    font-family: 'Space Grotesk', sans-serif;
  }
  
  .tag.ok { background: rgba(0,200,83,0.15); color: var(--vert); }
  .tag.wait { background: rgba(255,214,0,0.15); color: var(--accent); }
  .tag.fail { background: rgba(255,80,80,0.15); color: #ff5050; }
  
  .refresh-btn {
    display: block;
    margin: 24px auto 0;
    padding: 12px 32px;
    background: var(--vert);
    color: #000;
    border: none;
    border-radius: 100px;
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 0.9rem;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  .refresh-btn:hover { opacity: 0.85; }
  
  .empty {
    text-align: center;
    padding: 40px;
    color: #555;
    font-size: 0.9rem;
  }
</style>
</head>
<body>

<header>
  <div class="logo">💬</div>
  <div>
    <h1>WhatsApp CRM <span>Lite</span></h1>
    <p style="font-size:0.78rem;color:#666;margin-top:2px;">Burkina Faso · Mobile Money</p>
  </div>
  <span class="badge">● LIVE</span>
</header>

<div class="stats">
  <div class="stat-card blanc">
    <div class="label">Clients actifs</div>
    <div class="value">{{ total_clients }}</div>
  </div>
  <div class="stat-card vert">
    <div class="label">Paiements OK</div>
    <div class="value">{{ paie_ok }}</div>
  </div>
  <div class="stat-card jaune">
    <div class="label">En attente</div>
    <div class="value">{{ paie_attente }}</div>
  </div>
  <div class="stat-card blanc">
    <div class="label">Revenus (FCFA)</div>
    <div class="value">{{ revenus }}</div>
  </div>
</div>

<h2>Commandes récentes</h2>

{% if commandes %}
<table>
  <thead>
    <tr>
      <th>Date</th>
      <th>Client</th>
      <th>Montant</th>
      <th>Statut</th>
      <th>ID Transaction</th>
    </tr>
  </thead>
  <tbody>
    {% for c in commandes|reverse %}
    <tr>
      <td>{{ c.date[:16].replace('T', ' ') }}</td>
      <td>{{ c.nom }}</td>
      <td>{{ "{:,}".format(c.montant) }} FCFA</td>
      <td>
        {% if c.statut == 'ACCEPTED' %}
          <span class="tag ok">✓ Payé</span>
        {% elif c.statut == 'EN_ATTENTE' %}
          <span class="tag wait">⏳ En attente</span>
        {% else %}
          <span class="tag fail">✗ {{ c.statut }}</span>
        {% endif %}
      </td>
      <td>{{ c.transaction_id }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<div class="empty">
  <p>🕐 Aucune commande pour l'instant.</p>
  <p style="margin-top:8px;font-size:0.8rem;">Les commandes apparaîtront ici dès que les clients paieront via WhatsApp.</p>
</div>
{% endif %}

<button class="refresh-btn" onclick="location.reload()">↻ Actualiser</button>

</body>
</html>
"""

@app.route("/dashboard")
def dashboard():
    """Dashboard de gestion des commandes"""
    db = load_db()
    commandes = db.get("commandes", [])
    
    paie_ok = sum(1 for c in commandes if c.get("statut") == "ACCEPTED")
    paie_attente = sum(1 for c in commandes if c.get("statut") == "EN_ATTENTE")
    revenus = sum(c.get("montant", 0) for c in commandes if c.get("statut") == "ACCEPTED")
    revenus_str = f"{revenus:,}"
    
    return render_template_string(
        DASHBOARD_HTML,
        commandes=commandes,
        total_clients=len(db.get("clients", {})),
        paie_ok=paie_ok,
        paie_attente=paie_attente,
        revenus=revenus_str
    )

@app.route("/api/stats")
def api_stats():
    """API JSON pour récupérer les stats (pour intégration future)"""
    db = load_db()
    commandes = db.get("commandes", [])
    return jsonify({
        "total_clients": len(db.get("clients", {})),
        "total_commandes": len(commandes),
        "paiements_confirmes": sum(1 for c in commandes if c.get("statut") == "ACCEPTED"),
        "revenus_fcfa": sum(c.get("montant", 0) for c in commandes if c.get("statut") == "ACCEPTED"),
        "derniere_commande": commandes[-1] if commandes else None
    })

CHAT_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Chat Amina · Groq</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Space+Grotesk:wght@400;600;700&display=swap');
    :root { --vert:#00C853; --noir:#0A0A0A; --gris:#1A1A1A; --gris2:#2A2A2A; --texte:#E8E8E8; --accent:#FFD600; }
    * { margin:0; padding:0; box-sizing:border-box; }
    body { background:var(--noir); color:var(--texte); font-family:'Space Grotesk',sans-serif;
           height:100vh; display:flex; flex-direction:column; }

    /* ── Header ── */
    header { display:flex; align-items:center; gap:12px; padding:16px 20px;
             border-bottom:1px solid var(--gris2); flex-shrink:0; }
    .avatar { width:38px; height:38px; background:var(--vert); border-radius:50%;
              display:flex; align-items:center; justify-content:center; font-size:18px; }
    .hinfo h1 { font-size:1rem; font-weight:700; }
    .hinfo p  { font-size:0.72rem; color:#666; font-family:'IBM Plex Mono',monospace; }
    .clear-btn { margin-left:auto; padding:7px 16px; background:transparent;
                 border:1px solid var(--gris2); border-radius:100px; color:#666;
                 font-family:'Space Grotesk',sans-serif; font-size:0.78rem;
                 cursor:pointer; transition:all .2s; }
    .clear-btn:hover { border-color:#555; color:var(--texte); }

    /* ── Message thread ── */
    #thread { flex:1; overflow-y:auto; padding:24px 20px; display:flex;
              flex-direction:column; gap:14px; }
    .bubble { max-width:78%; padding:12px 16px; border-radius:18px;
              font-size:0.92rem; line-height:1.55; white-space:pre-wrap; word-break:break-word; }
    .bubble.user { align-self:flex-end; background:var(--vert); color:#000;
                   border-bottom-right-radius:4px; }
    .bubble.ai   { align-self:flex-start; background:var(--gris);
                   border:1px solid var(--gris2); border-bottom-left-radius:4px; }
    .empty-state { align-self:center; margin:auto; text-align:center; color:#444; }
    .empty-state .icon { font-size:2.5rem; margin-bottom:12px; }
    .empty-state p { font-size:0.85rem; }

    /* ── Input bar ── */
    form { display:flex; gap:10px; padding:14px 20px;
           border-top:1px solid var(--gris2); flex-shrink:0; }
    textarea { flex:1; background:var(--gris); border:1px solid var(--gris2);
               border-radius:14px; color:var(--texte); font-family:'Space Grotesk',sans-serif;
               font-size:0.92rem; padding:12px 16px; resize:none; outline:none;
               max-height:120px; line-height:1.5; }
    textarea:focus { border-color:var(--vert); }
    button[type=submit] { align-self:flex-end; width:44px; height:44px; flex-shrink:0;
                          background:var(--vert); border:none; border-radius:50%;
                          font-size:1.1rem; cursor:pointer; transition:opacity .2s;
                          display:flex; align-items:center; justify-content:center; }
    button[type=submit]:hover { opacity:.85; }

    /* ── Model tag ── */
    .model-pill { align-self:center; padding:4px 12px; margin-bottom:4px;
                  background:rgba(0,200,83,.08); border:1px solid rgba(0,200,83,.2);
                  border-radius:100px; font-family:'IBM Plex Mono',monospace;
                  font-size:0.68rem; color:var(--vert); flex-shrink:0;
                  text-align:center; }
  </style>
</head>
<body>

<header>
  <div class="avatar">🛍️</div>
  <div class="hinfo">
    <h1>Amina</h1>
    <p>Assistante commerciale · llama-3.3-70b-versatile</p>
  </div>
  <form action="/test-ai/clear" method="POST" style="margin:0;">
    <button class="clear-btn" type="submit">✕ Effacer</button>
  </form>
</header>

<div class="model-pill">Groq API · llama-3.3-70b-versatile</div>

<div id="thread">
  {% if not history %}
  <div class="empty-state">
    <div class="icon">💬</div>
    <p>Envoie un message pour démarrer<br>une conversation avec Amina.</p>
  </div>
  {% endif %}
  {% for msg in history %}
    <div class="bubble {{ msg.role if msg.role == 'user' else 'ai' }}">{{ msg.content }}</div>
  {% endfor %}
</div>

<form method="POST" id="chatForm">
  <textarea id="msg" name="message" rows="1"
            placeholder="Écris ton message…"
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();this.form.requestSubmit();}"></textarea>
  <button type="submit">➤</button>
</form>

<script>
  const thread = document.getElementById('thread');
  thread.scrollTop = thread.scrollHeight;
  const ta = document.getElementById('msg');
  ta.addEventListener('input', () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  });
</script>
</body>
</html>
"""

@app.route("/test-ai", methods=["GET", "POST"])
def test_ai():
    """
    Chat multi-tours avec Amina (Groq) stocké en session Flask.
    GET  → affiche la conversation en cours + formulaire
    POST → ajoute le message, appelle Groq, redirige vers GET
    """
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if message:
            history = session.get("chat_history", [])
            history.append({"role": "user", "content": message})
            reponse = ask_groq(history, SYSTEM_PROMPT)
            history.append({"role": "assistant", "content": reponse})
            session["chat_history"] = history
        return redirect(url_for("test_ai"))

    history = session.get("chat_history", [])
    return render_template_string(CHAT_HTML, history=history)

app.route("/submit-onboarding", methods=["POST"])
def submit_onboarding():
    data = request.json
    message = (
        f"🆕 *Nouvelle commande !*\n\n"
        f"🏪 *Boutique:* {data.get('nom_boutique')}\n"
        f"📍 *Ville:* {data.get('ville')}\n"
        f"📱 *WhatsApp:* {data.get('whatsapp')}\n"
        f"💰 *Orange Money:* {data.get('orange_money')}\n"
        f"📧 *Email:* {data.get('email')}\n"
        f"🛍️ *Produits:* {data.get('produits')}\n"
        f"💎 *Formule:* {data.get('tarif')}\n"
        f"📝 *Message:* {data.get('message_perso')}"
    )
    envoyer_message_whatsapp("whatsapp:+22603141464", message)
    return jsonify({"status": "ok"})


@app.route("/test-ai/clear", methods=["POST"])
def test_ai_clear():
    """Efface l'historique de conversation du test-ai."""
    session.pop("chat_history", None)
    return redirect(url_for("test_ai"))
  

@app.route("/onboarding")
def onboarding():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "onboarding.html"), encoding="utf-8") as f:
        return f.read()
      
@app.route("/")
def index():
    return jsonify({
        "status": "✅ WhatsApp CRM Lite - En ligne",
        "endpoints": {
            "/webhook/whatsapp": "POST - Webhook Twilio",
            "/webhook/paiement": "POST - Webhook CinetPay",
            "/dashboard": "GET - Interface de gestion",
            "/api/stats": "GET - Statistiques JSON",
            "/test-ai": "GET/POST - Tester la clé Groq API"
        }
    })

# =============================================
# LANCEMENT
# =============================================
if __name__ == "__main__":
    print("=" * 50)
    print("  WhatsApp CRM Lite - Démarrage")
    print("  Dashboard: http://localhost:5000/dashboard")
    print("=" * 50)
    app.run(debug=True, port=5000, host="0.0.0.0")
