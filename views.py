from flask import Blueprint, render_template, request
from models import db, Order

bp = Blueprint("views", __name__)

@bp.route("/")
def home():
    return render_template("home.html")

@bp.route("/track", methods=["GET", "POST"])
def track():
    result = None
    if request.method == "POST":
        tracking_number = request.form.get("tracking_number")
        result = Order.query.filter_by(tracking_number=tracking_number).first()
    return render_template("track.html", result=result)