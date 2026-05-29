from flask import Flask, render_template, request, redirect, url_for
import json
import os

app = Flask(__name__)

DB_FILE = "Db.json"


# -----------------------
# INIT DB
# -----------------------
def load_db():
    if not os.path.exists(DB_FILE):
        return {"shops": []}
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)


# -----------------------
# HOME / ONBOARDING
# -----------------------
@app.route("/")
def home():
    return render_template("onboarding.html")


# -----------------------
# CREATE SHOP
# -----------------------
@app.route("/create-shop", methods=["POST"])
def create_shop():
    data = load_db()

    shop_name = request.form.get("shop_name")

    shop = {
        "id": str(len(data["shops"]) + 1),
        "name": shop_name,
        "twilio_number": "+1 415 XXX XXXX",
        "sandbox_code": "join sandbox-amina"
    }

    data["shops"].append(shop)
    save_db(data)

    return redirect(url_for("dashboard", shop_id=shop["id"]))


# -----------------------
# DASHBOARD
# -----------------------
@app.route("/dashboard/<shop_id>")
def dashboard(shop_id):
    data = load_db()

    shop = next((s for s in data["shops"] if s["id"] == shop_id), None)

    if not shop:
        return "Shop introuvable"

    return render_template("Tableau de bord.html", shop=shop)


# -----------------------
# TWILIO WEBHOOK (AMINA BOT)
# -----------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    msg = request.form.get("Body")

    reply = f"Amina 🤖 : j'ai reçu -> {msg}"

    return f"""
    <Response>
        <Message>{reply}</Message>
    </Response>
    """


# -----------------------
# RUN APP
# -----------------------
if __name__ == "__main__":
    app.run(debug=True)
