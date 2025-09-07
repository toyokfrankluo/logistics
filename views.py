# views.py
from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file
from models import db, CarrierAgent, Shipment, Customer, BankAccount, ManualTrack
from flask_login import login_required, logout_user
from datetime import datetime
from utils import export_invoice
import requests
import json

views = Blueprint("views", __name__)

# -------------------------------
# API 轨迹获取函数
# -------------------------------
def fetch_tracking_from_api(agent: CarrierAgent, tracking_number: str):
    """
    根据不同的代理调用不同 API
    """
    if not agent or not agent.api_url or not agent.supports_api:
        return None, "代理不支持 API 抓取"

    try:
        # ========================
        # 1. YWTYGJ 接口 (rtb56)
        # ========================
        if "rtb56.com" in (agent.api_url or ""):
            payload = {
                "appToken": agent.app_token,
                "appKey": agent.app_key,
                "serviceMethod": "gettrack",
                "paramsJson": json.dumps({"tracking_number": tracking_number})
            }
            resp = requests.post(agent.api_url, data=payload, timeout=15)
            print("=== API 原始返回 (rtb56) ===", resp.text)

            if resp.status_code != 200:
                return None, f"API返回错误 {resp.status_code}"

            data = resp.json()
            if not data.get("success"):
                # 返回的 message 在 cnmessage/enmessage
                return None, data.get("cnmessage") or data.get("enmessage") or "接口调用失败"

            # 轨迹在 data[0]["details"]
            tracks = []
            if data.get("data") and isinstance(data["data"], list):
                details = data["data"][0].get("details", [])
                for d in details:
                    tracks.append({
                        "time": d.get("track_occur_date"),
                        "location": d.get("track_location"),
                        "description": d.get("track_description")
                    })
            return tracks, None

        # ========================
        # 2. NEXTSLS 接口 (nextsls)
        #    使用 client_reference（客户单号）去查询
        # ========================
        elif "nextsls.com" in (agent.api_url or ""):
            url = agent.api_url
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {agent.app_token}"  # token 存在 app_token 字段
            }
            payload = {
                "access_token": agent.app_token,
                "shipment": {
                    "shipment_id": "",
                    "client_reference": tracking_number,  # 使用客户单号
                    "tracking_number": "",
                    "parcel_number": "",
                    "waybill_number": "",
                    "language": "zh"
                }
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            print("=== API 原始返回 (nextsls) ===", resp.text)

            if resp.status_code != 200:
                return None, f"API返回错误 {resp.status_code}"

            data = resp.json()
            if data.get("status") != 1:
                return None, data.get("info", "接口调用失败")

            traces = data.get("data", {}).get("shipment", {}).get("traces", [])
            tracks = []
            for t in traces:
                ts = t.get("time")
                if isinstance(ts, int):
                    ts = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                tracks.append({
                    "time": ts,
                    "location": t.get("location", ""),
                    "description": t.get("info", "")
                })
            return tracks, None

        # ========================
        # 3. 默认情况（兼容 GET 返回 JSON）
        # ========================
        else:
            resp = requests.get(agent.api_url, params={
                "appKey": agent.app_key,
                "appToken": agent.app_token,
                "tracking_number": tracking_number
            }, timeout=10)
            print("=== API 原始返回 (default) ===", resp.text)

            if resp.status_code != 200:
                return None, f"API返回错误 {resp.status_code}"

            data = resp.json()
            # 尝试多种常见字段
            if isinstance(data, dict):
                if "tracks" in data:
                    return data["tracks"], None
                if "data" in data and data["data"]:
                    return data["data"], None
                if "result" in data and isinstance(data["result"], dict) and "list" in data["result"]:
                    return data["result"]["list"], None
            return None, "未找到轨迹字段"

    except Exception as e:
        return None, f"API请求失败: {str(e)}"


# -------------------------------
# 代理管理
# -------------------------------
@views.route("/agents", methods=["GET", "POST"])
@login_required
def agents():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("代理名称不能为空", "danger")
            return redirect(url_for("views.agents"))

        a = CarrierAgent(
            name=name,
            api_url=request.form.get("api_url"),
            app_key=request.form.get("app_key"),
            app_token=request.form.get("app_token"),
            customer_code=request.form.get("customer_code"),
            is_active=True
        )
        db.session.add(a)
        db.session.commit()
        flash("代理已添加", "success")
        return redirect(url_for("views.agents"))

    data = CarrierAgent.query.filter_by(is_active=True).all()
    return render_template("agent.html", agents=data)


@views.route("/agents/<int:agent_id>/edit", methods=["GET", "POST"])
@login_required
def edit_agent(agent_id):
    a = CarrierAgent.query.get_or_404(agent_id)
    if request.method == "POST":
        a.name = request.form.get("name", a.name)
        a.api_url = request.form.get("api_url", a.api_url)
        a.app_key = request.form.get("app_key", a.app_key)
        a.app_token = request.form.get("app_token", a.app_token)
        a.customer_code = request.form.get("customer_code", a.customer_code)
        db.session.commit()
        flash("代理已更新", "success")
        return redirect(url_for("views.agents"))

    return render_template("edit_agent.html", agent=a)


@views.route("/agents/<int:agent_id>/delete", methods=["POST"])
@login_required
def delete_agent(agent_id):
    a = CarrierAgent.query.get_or_404(agent_id)
    Shipment.query.filter_by(agent_id=a.id).update({"agent_id": None})  # 解绑运单
    a.is_active = False
    db.session.commit()
    flash("代理已删除（软删除）", "success")
    return redirect(url_for("views.agents"))


# -------------------------------
# 运单管理
# -------------------------------
@views.route("/shipments")
@login_required
def shipments():
    data = Shipment.query.order_by(Shipment.created_at.desc()).all()
    return render_template("shipments.html", shipments=data)


@views.route("/shipments/add", methods=["GET", "POST"])
@login_required
def add_shipment():
    if request.method == "POST":
        tracking_number = request.form.get("tracking_number").strip()
        if Shipment.query.filter_by(tracking_number=tracking_number).first():
            flash(f"运单号 {tracking_number} 已存在，请更换", "danger")
            return redirect(url_for("views.add_shipment"))

        shipment = Shipment(
            tracking_number=tracking_number,
            customer_id=request.form.get("customer_id") or None,
            agent_id=request.form.get("agent_id") or None,
            carrier_id=request.form.get("carrier_id"),
            origin=request.form.get("origin"),
            destination=request.form.get("destination"),
            channel=request.form.get("channel"),
            product_type=request.form.get("product_type"),
            pieces=int(request.form.get("pieces") or 1),
            weight=float(request.form.get("weight") or 0),
            unit_price=float(request.form.get("unit_price") or 0),
            surcharge_extra=float(request.form.get("surcharge_extra") or 0),
            operation_fee=float(request.form.get("operation_fee") or 0),
            high_value_fee=float(request.form.get("high_value_fee") or 0),
            status="已录入",
            note=request.form.get("note")
        )
        shipment.fee = shipment.weight * shipment.unit_price + shipment.surcharge_extra + shipment.operation_fee + shipment.high_value_fee

        db.session.add(shipment)
        db.session.commit()
        flash("运单已保存", "success")
        return redirect(url_for("views.shipments"))

    customers = Customer.query.all()
    agents = CarrierAgent.query.all()
    destinations = ["美国", "加拿大", "英国", "德国"]

    return render_template("add_shipment.html", customers=customers, agents=agents, destinations=destinations)


@views.route("/shipments/edit/<int:shipment_id>", methods=["GET", "POST"])
@login_required
def edit_shipment(shipment_id):
    s = Shipment.query.get_or_404(shipment_id)
    if request.method == "POST":
        new_tracking_number = request.form.get("tracking_number", s.tracking_number)
        duplicate = Shipment.query.filter(
            Shipment.tracking_number == new_tracking_number,
            Shipment.id != s.id
        ).first()
        if duplicate:
            flash(f"运单号 {new_tracking_number} 已存在", "danger")
            return redirect(url_for("views.edit_shipment", shipment_id=shipment_id))

        s.tracking_number = new_tracking_number
        s.customer_id = request.form.get("customer_id") or None
        s.agent_id = request.form.get("agent_id") or None
        s.origin = request.form.get("origin")
        s.destination = request.form.get("destination")
        s.channel = request.form.get("channel")
        s.product_type = request.form.get("product_type")
        s.pieces = int(request.form.get("pieces") or 1)
        s.weight = float(request.form.get("weight") or 0)
        s.unit_price = float(request.form.get("unit_price") or 0)
        s.surcharge_extra = float(request.form.get("surcharge_extra") or 0)
        s.operation_fee = float(request.form.get("operation_fee") or 0)
        s.high_value_fee = float(request.form.get("high_value_fee") or 0)
        s.fee = s.weight * s.unit_price + s.surcharge_extra + s.operation_fee + s.high_value_fee
        s.note = request.form.get("note", s.note)

        db.session.commit()
        flash("运单已更新", "success")
        return redirect(url_for("views.shipments"))

    customers = Customer.query.all()
    agents = CarrierAgent.query.all()
    destinations = ["美国", "加拿大", "英国", "德国"]

    return render_template("add_shipment.html", shipment=s, customers=customers, agents=agents, destinations=destinations)


@views.route("/shipments/delete/<int:shipment_id>", methods=["POST"])
@login_required
def delete_shipment(shipment_id):
    s = Shipment.query.get_or_404(shipment_id)
    db.session.delete(s)
    db.session.commit()
    flash("运单已删除", "success")
    return redirect(url_for("views.shipments"))


# -------------------------------
# 银行账户管理
# -------------------------------
@views.route("/bank_accounts", methods=["GET", "POST"])
@login_required
def bank_accounts():
    if request.method == "POST":
        acc = BankAccount(
            account_type=request.form.get("account_type", "private"),
            bank_name=request.form.get("bank_name"),
            account_name=request.form.get("account_name"),
            account_no=request.form.get("account_no"),
            remark=request.form.get("remark")
        )
        db.session.add(acc)
        db.session.commit()
        flash("银行账户已添加", "success")
        return redirect(url_for("views.bank_accounts"))

    accounts = BankAccount.query.all()
    return render_template("bank_accounts.html", accounts=accounts)


# -------------------------------
# 手工轨迹
# -------------------------------
@views.route("/shipments/<int:shipment_id>/tracks", methods=["GET", "POST"])
@login_required
def manual_tracks(shipment_id):
    shipment = Shipment.query.get_or_404(shipment_id)
    if request.method == "POST":
        track = ManualTrack(
            shipment_id=shipment.id,
            description=request.form.get("description"),
            location=request.form.get("location"),
            happen_time=datetime.utcnow(),
            author="admin"
        )
        db.session.add(track)
        db.session.commit()
        flash("轨迹已添加", "success")
        return redirect(url_for("views.manual_tracks", shipment_id=shipment.id))

    events = ManualTrack.query.filter_by(shipment_id=shipment.id).order_by(ManualTrack.happen_time.desc()).all()
    return render_template("shipment_events.html", shipment=shipment, events=events)


# -------------------------------
# 客户管理
# -------------------------------
@views.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bankinfo = request.form.get("bankinfo", "").strip()
        if not name:
            flash("客户名称不能为空", "danger")
            return redirect(url_for("views.customers"))

        c = Customer(name=name, bank_info=bankinfo)
        db.session.add(c)
        db.session.commit()
        flash("客户已添加", "success")
        return redirect(url_for("views.customers"))

    data = Customer.query.all()
    return render_template("customers.html", customers=data)


# -------------------------------
# 财务模块
# -------------------------------
@views.route("/finance", methods=["GET", "POST"])
@login_required
def finance():
    customers = Customer.query.all()
    accounts = BankAccount.query.all()

    selected_customer_id = request.form.get("customer_id")
    date_from = request.form.get("date_from")
    date_to = request.form.get("date_to")

    query = Shipment.query
    if selected_customer_id:
        query = query.filter_by(customer_id=selected_customer_id)
    if date_from:
        query = query.filter(Shipment.created_at >= date_from)
    if date_to:
        query = query.filter(Shipment.created_at <= date_to)

    shipments = query.all()
    total_fees = sum([s.fee for s in shipments])
    total_shipments = len(shipments)

    if request.form.get("export"):
        customer_name = "全部客户"
        if selected_customer_id:
            customer = Customer.query.get(selected_customer_id)
            customer_name = customer.name if customer else "未知客户"

        orders = []
        for s in shipments:
            orders.append({
                "date": s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
                "order_no": s.tracking_number,
                "service_no": s.carrier_id or "",
                "qty": s.pieces,
                "type": s.product_type or "",
                "weight": s.weight,
                "destination": s.destination or "",
                "channel": s.channel or "",
                "fee": s.fee,
                "summary": s.note or ""
            })

        # 直接传 accounts 列表给 export_invoice（函数会识别 ORM 对象）
        company_info = {
            "公司名称": "深圳市星睿国际物流有限公司",
            "地址": "深圳市宝安区福永镇福海街道同富路3号惠明盛工业园5栋一楼"
        }

        # 传递 date_from/date_to 给导出函数
        filename = export_invoice(company_info, customer_name, orders, accounts,
                                  date_from=date_from or None, date_to=date_to or None)
        return send_file(filename, as_attachment=True)

    return render_template("finance.html",
                           customers=customers,
                           accounts=accounts,
                           shipments=shipments,
                           total_shipments=total_shipments,
                           total_fees=total_fees,
                           selected_customer_id=selected_customer_id,
                           date_from=date_from,
                           date_to=date_to)


# -------------------------------
# 轨迹查询（合并手工 + API）
# -------------------------------
@views.route("/track", methods=["GET", "POST"])
@login_required
def track():
    agents = CarrierAgent.query.filter_by(is_active=True).all()
    customers = Customer.query.all()
    carriers = {str(a.id): {"name": a.name} for a in agents}

    message, results, default_text = None, {}, ""

    if request.method == "POST":
        customer_id = request.form.get("customer_id")
        agent_id = request.form.get("agent_id")
        numbers = request.form.get("numbers", "").strip().splitlines()

        query = Shipment.query
        if customer_id:
            query = query.filter_by(customer_id=customer_id)
        if agent_id:
            query = query.filter_by(agent_id=agent_id)

        if not numbers or numbers == [""]:
            shipments = query.all()
            numbers = [s.tracking_number for s in shipments]

        if not numbers:
            message = "未找到运单号"
        else:
            for no in numbers:
                no = no.strip()
                if not no:
                    continue

                s = Shipment.query.filter_by(tracking_number=no).first()
                all_tracks = []
                err = None

                # 1. 手工轨迹（显示不带标签）
                if s:
                    manual_events = s.manual_tracks
                    if manual_events:
                        for e in manual_events:
                            all_tracks.append(f"{e.happen_time.strftime('%Y-%m-%d %H:%M')} {e.location or ''} {e.description}")

                # 2. API 轨迹（显示不带 [API] 标签）
                if s and s.agent:
                    api_tracks, api_err = fetch_tracking_from_api(s.agent, no)
                    if api_tracks:
                        if isinstance(api_tracks, list):
                            for ev in api_tracks:
                                time = ev.get("time") or ev.get("happen_time") or ""
                                loc = ev.get("location") or ""
                                desc = ev.get("description") or ev.get("status") or ""
                                all_tracks.append(f"{time} {loc} {desc}")
                        elif isinstance(api_tracks, str):
                            all_tracks.append(api_tracks)
                    if api_err:
                        err = api_err

                # 3. 如果都没有
                if not all_tracks:
                    all_tracks.append("暂无轨迹")

                results[no] = {"tracks": "\n".join(all_tracks), "error": err}

            message = f"共查询到 {len(results)} 条结果"

    return render_template("track.html",
                           agents=agents,
                           customers=customers,
                           carriers=carriers,
                           results=results,
                           message=message,
                           default_text=default_text,
                           public_mode=False)


# -------------------------------
# 登出
# -------------------------------
@views.route("/logout")
@login_required
def logout():
    logout_user()
    flash("您已登出", "success")
    return redirect(url_for("login"))