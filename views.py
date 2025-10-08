from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file
from models import db, CarrierAgent, Shipment, Customer, BankAccount, ManualTrack
from flask_login import login_required, logout_user
from models import db, CarrierAgent, Shipment, Customer, BankAccount, ManualTrack
from datetime import datetime, timedelta
from utils import export_invoice
import requests
import json
import os
import time

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
        # 1. YWTYGJ 接口 (rtb56) 和 txfba.com 接口
        # ========================
        if "rtb56.com" in (agent.api_url or "") or "txfba.com" in (agent.api_url or ""):
            payload = {
                "appToken": agent.app_token,
                "appKey": agent.app_key,
                "serviceMethod": "gettrack",
                "paramsJson": json.dumps({"tracking_number": tracking_number})
            }
            
            print(f"🔄 发送POST请求到RTB56/txfba接口: {agent.api_url}")
            print(f"📦 请求数据: {payload}")
            
            resp = requests.post(agent.api_url, data=payload, timeout=15)
            print("=== API 原始返回 (RTB56/txfba) ===", resp.text)

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
        #    使用 shipment_id 去查询
        # ========================
        elif "nextsls.com" in (agent.api_url or ""):
            # 根据 tracking_number 获取对应的 shipment
            shipment = Shipment.query.filter_by(tracking_number=tracking_number).first()
            
            # 修复：处理shipment_id缺失的情况
            if not shipment:
                # 尝试直接使用tracking_number作为shipment_id
                shipment_id = tracking_number
                print(f"⚠️ 未找到shipment记录，使用tracking_number作为shipment_id: {shipment_id}")
            elif not shipment.shipment_id:
                # 有shipment记录但没有shipment_id，使用tracking_number
                shipment_id = tracking_number
                print(f"⚠️ shipment记录缺少shipment_id，使用tracking_number: {shipment_id}")
            else:
                shipment_id = shipment.shipment_id

            url = agent.api_url
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {agent.app_token}"  # token 存在 app_token 字段
            }
            payload = {
                "shipment": {
                    "shipment_id": shipment_id,  # 使用 shipment_id 或 tracking_number
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
        # 3. 默认情况（统一使用POST请求）
        # ========================
        else:
            # 统一使用POST请求，支持更多接口
            payload = {
                "appKey": agent.app_key,
                "appToken": agent.app_token,
                "tracking_number": tracking_number
            }
            
            print(f"🔄 发送默认POST请求到: {agent.api_url}")
            print(f"📦 请求数据: {payload}")
            
            resp = requests.post(agent.api_url, data=payload, timeout=10)
            print("=== API 原始返回 (default POST) ===", resp.text)

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
                # 添加对错误信息的处理
                if "code" in data and data["code"] != 200:
                    return None, data.get("message", "接口返回错误")
            return None, "未找到轨迹字段"

    except Exception as e:
        return None, f"API请求失败: {str(e)}"


# =============== 新增：去重同步函数 ===============
def sync_tracking_to_supabase(shipment, tracks):
    """
    同步轨迹数据到Supabase，避免重复数据
    """
    try:
        supabase_url = os.environ.get('SUPABASE_URL') or 'https://qxfzltryagnyiderbljf.supabase.co'
        supabase_key = os.environ.get('SUPABASE_KEY') or 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF4ZnpsdHJ5YWdueWlkZXJibGpmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc3NTE4ODIsImV4cCI6MjA3MzMyNzg4Mn0.K90fwI3dwNJRXvIutvxhzzyVLjzgO7bfykAE26ZqGX4'
        
        success_count = 0
        error_count = 0
        
        for track in tracks:
            try:
                # 生成唯一标识符，用于检查重复
                event_time = track.get('time')
                if not event_time:
                    event_time = datetime.utcnow().isoformat()
                
                location = track.get('location', '')
                description = track.get('description', track.get('info', track.get('status', '')))
                
                # 检查是否已存在相同记录
                check_response = requests.get(
                    f"{supabase_url}/rest/v1/shipment_tracking_details",
                    params={
                        "tracking_number": f"eq.{shipment.tracking_number}",
                        "event_time": f"eq.{event_time}",
                        "description": f"eq.{description}",
                        "select": "id"
                    },
                    headers={
                        "Authorization": f"Bearer {supabase_key}",
                        "apikey": supabase_key
                    },
                    timeout=5
                )
                
                # 如果记录已存在，跳过插入
                if check_response.status_code == 200 and len(check_response.json()) > 0:
                    print(f"⏭️ 跳过重复轨迹: {description[:50]}...")
                    continue
                
                track_data = {
                    "tracking_number": shipment.tracking_number,
                    "event_time": event_time,
                    "location": location,
                    "description": description
                }
                
                # 插入新记录
                response = requests.post(
                    f"{supabase_url}/rest/v1/shipment_tracking_details",
                    headers={
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "apikey": supabase_key,
                        "Prefer": "return=minimal"
                    },
                    data=json.dumps(track_data),
                    timeout=10
                )
                
                if response.status_code in [200, 201, 204]:
                    success_count += 1
                    print(f"✅ 轨迹同步成功: {description[:50]}...")
                else:
                    error_count += 1
                    print(f"❌ 轨迹同步失败: {response.status_code}")
                    
            except Exception as e:
                error_count += 1
                print(f"🔥 单条轨迹同步异常: {str(e)}")
        
        return success_count, error_count
        
    except Exception as e:
        print(f"💥 轨迹同步过程出错: {str(e)}")
        return 0, 1


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
    query = Shipment.query.order_by(Shipment.created_at.desc())

    # 从 URL 获取查询参数
    customer = request.args.get("customer")
    agent = request.args.get("agent")
    tracking_number = request.args.get("tracking_number")

    if customer:
        query = query.join(Customer).filter(Customer.name.ilike(f"%{customer}%"))
    if agent:
        query = query.join(CarrierAgent).filter(CarrierAgent.name.ilike(f"%{agent}%"))
    if tracking_number:
        query = query.filter(Shipment.tracking_number.ilike(f"%{tracking_number}%"))

    data = query.all()
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
            shipment_id=request.form.get("shipment_id"),
            third_party_tracking_number=request.form.get("third_party_tracking_number"),
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
        
        # =============== 优化后的Supabase同步代码 ===============
        try:
            # 从环境变量获取Supabase配置（更安全）
            supabase_url = os.environ.get('SUPABASE_URL') or 'https://qxfzltryagnyiderbljf.supabase.co'
            supabase_key = os.environ.get('SUPABASE_KEY') or 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF4ZnpsdHJ5YWdueWlkZXJibGpmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc3NTE4ODIsImV4cCI6MjA3MzMyNzg4Mn0.K90fwI3dwNJRXvIutvxhzzyVLjzgO7bfykAE26ZqGX4'
            # 获取客户名称
            customer_name = "未知客户"
            if shipment.customer_id:
                customer = Customer.query.get(shipment.customer_id)
                if customer:
                    customer_name = customer.name
            
            # 准备同步数据
            data_to_insert = {
                "tracking_number": shipment.tracking_number,
                "customer_name": customer_name,
                "current_location": shipment.origin or "仓库",
                "status": "pending",
                "notes": f"目的地: {shipment.destination} | 渠道: {shipment.channel} | 重量: {shipment.weight}kg"
            }
            
            # 打印调试信息
            print(f"🔄 尝试同步到Supabase: {tracking_number}")
            
            response = requests.post(
                f"{supabase_url}/rest/v1/shipment_tracking",
                headers={
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "apikey": supabase_key,
                    "Prefer": "return=minimal"
                },
                data=json.dumps(data_to_insert),
                timeout=10  # 添加超时
            )
            
            # 详细的响应处理
            if response.status_code in [200, 201, 204]:
                print(f"✅ 成功同步到Supabase: {tracking_number}")
                flash("运单已保存并同步到查询系统", "success")
            else:
                error_msg = f"❌ 同步失败: {response.status_code} - {response.text}"
                print(error_msg)
                flash("运单已保存，但同步到查询系统失败", "warning")
                
        except requests.exceptions.Timeout:
            print("⏰ Supabase请求超时")
            flash("运单已保存，但同步到查询系统超时", "warning")
        except requests.exceptions.ConnectionError:
            print("🔌 网络连接错误")
            flash("运单已保存，但无法连接到查询系统", "warning")
        except Exception as e:
            error_msg = f"🔥 同步异常: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            flash("运单已保存，但同步到查询系统时出现异常", "warning")
        # =============== 同步代码结束 ===============
        
        # =============== 修改：轨迹同步代码 ===============
        try:
            # 只有有代理的运单才获取轨迹
            if shipment.agent_id:
                agent = CarrierAgent.query.get(shipment.agent_id)
                if agent and agent.supports_api:
                    print(f"🔄 尝试获取轨迹信息: {shipment.tracking_number}")
                    
                    # 调用您的轨迹API获取函数
                    tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                    
                    if tracks and not error:
                        print(f"✅ 获取到 {len(tracks)} 条轨迹信息")
                        
                        # 使用优化后的同步函数
                        success_count, error_count = sync_tracking_to_supabase(shipment, tracks)
                        print(f"📊 轨迹同步结果: 成功 {success_count}, 失败 {error_count}")
                    else:
                        print(f"⚠️ 无法获取轨迹: {error}")
                        
        except Exception as e:
            print(f"🔥 轨迹同步异常: {str(e)}")
            import traceback
            traceback.print_exc()
        # =============== 轨迹同步结束 ===============
        
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
        s.shipment_id = request.form.get("shipment_id", s.shipment_id)  # 使用 shipment_id 替换 agent_tracking_number
        s.third_party_tracking_number = request.form.get("third_party_tracking_number", s.third_party_tracking_number)
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
        
        # =============== 新增代码：同步手工轨迹到Supabase ===============
        try:
            # 更新Supabase中的轨迹信息
            supabase_url = os.environ.get('SUPABASE_URL') or 'https://qxfzltryagnyiderbljf.supabase.co'
            supabase_key = os.environ.get('SUPABASE_KEY') or 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF4ZnpsdHJ5YWdueWlkZXJibGpmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc3NTE4ODIsImV4cCI6MjA3MzMyNzg4Mn0.K90fwI3dwNJRXvIutvxhzzyVLjzgO7bfykAE26ZqGX4'
            
            # 更新当前位置和状态
            update_data = {
                "current_location": request.form.get("location"),
                "status": "in_transit",  # 手工添加轨迹通常表示运输中
                "notes": f"手工更新: {request.form.get('description')}",
                "updated_at": datetime.utcnow().isoformat()
            }
            
            response = requests.patch(
                f"{supabase_url}/rest/v1/shipment_tracking?tracking_number=eq.{shipment.tracking_number}",
                headers={
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "apikey": supabase_key,
                    "Prefer": "return=minimal"
                },
                data=json.dumps(update_data)
            )
            
            if response.status_code in [200, 201, 204]:
                print(f"手工轨迹同步成功: {shipment.tracking_number}")
            else:
                print(f"手工轨迹同步失败: {response.status_code}")
                
        except Exception as e:
            print(f"手工轨迹同步异常: {str(e)}")
        # =============== 新增代码结束 ===============
        
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
# 17Track 轨迹查询
# -------------------------------
@views.route("/track_17track", methods=["GET", "POST"])
@login_required
def track_17track():
    """
    17Track轨迹查询功能
    """
    message, results, default_text = None, {}, ""
    
    if request.method == "POST":
        numbers = request.form.get("numbers", "").strip().splitlines()
        
        if not numbers or numbers == [""]:
            message = "请输入要查询的运单号"
        else:
            for no in numbers:
                no = no.strip()
                if not no:
                    continue
                    
                # 调用17Track API进行查询
                tracks, err = fetch_17track_tracking(no)
                
                if err:
                    results[no] = {"tracks": "", "error": err}
                else:
                    results[no] = {"tracks": tracks, "error": None}
                    
            message = f"共查询到 {len(results)} 条结果"
    
    return render_template("track_17track.html",
                           results=results,
                           message=message,
                           default_text=default_text)


def fetch_17track_tracking(tracking_number):
    """
    调用17Track API获取轨迹信息
    """
    try:
        # 17Track API 调用逻辑
        # 这里需要根据17Track的实际API文档进行实现
        # 以下是示例代码，需要根据实际情况修改
        
        # 示例：使用17Track的API
        api_url = "https://api.17track.net/track/v2/gettrackinfo"
        headers = {
            "Content-Type": "application/json",
            "17token": "YOUR_17TRACK_API_TOKEN"  # 需要替换为实际的API token
        }
        
        payload = {
            "number": tracking_number,
            "carrier": None  # 自动识别快递公司
        }
        
        response = requests.post(api_url, headers=headers, json=payload, timeout=15)
        
        if response.status_code != 200:
            return None, f"API返回错误 {response.status_code}"
            
        data = response.json()
        
        # 解析17Track返回的数据
        if data.get("status") == 200 and data.get("data"):
            tracks = []
            for event in data["data"][0].get("track", []):
                tracks.append(f"{event.get('time')} {event.get('location')} {event.get('description')}")
            
            return "\n".join(tracks), None
        else:
            return None, data.get("message", "查询失败")
            
    except Exception as e:
        return None, f"API请求失败: {str(e)}"


# -------------------------------
# 登出
# -------------------------------
@views.route("/logout")
@login_required
def logout():
    logout_user()
    flash("您已登出", "success")
    return redirect(url_for("login"))

# -------------------------------
# 手动同步路由
# -------------------------------
@views.route("/admin/sync-to-supabase")
@login_required
def sync_to_supabase():
    """手动同步所有运单基本信息到Supabase"""
    try:
        supabase_url = os.getenv('SUPABASE_URL') or 'https://qxfzltryagnyiderbljf.supabase.co'
        supabase_key = os.getenv('SUPABASE_KEY') or 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc極IiOiJzdXBhYmFzZSIsInJlZiI6InF4ZnpsdHJ5YWdueWlkZXJibGpmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc3NTE4ODIsImV4cCI6MjA3MzMyNzg4Mn0.K90fwI3dwNJRXvIutvxhzzyVLjzgO7bfykAE26ZqGX4'
        
        if not supabase_url or not supabase_key:
            flash("Supabase配置缺失", "danger")
            return redirect(url_for("views.shipments"))
        
        # 获取所有运单
        shipments = Shipment.query.all()
        success_count = 0
        error_count = 0
        
        for shipment in shipments:
            try:
                # 获取客户名称
                customer_name = "未知客户"
                if shipment.customer_id:
                    customer = Customer.query.get(shipment.customer_id)
                    if customer:
                        customer_name = customer.name
                
                # 准备数据
                data_to_insert = {
                    "tracking_number": shipment.tracking_number,
                    "customer_name": customer_name,
                    "current_location": shipment.origin or "仓库",
                    "status": "pending",
                    "notes": f"目的地: {shipment.destination} | 渠道: {shipment.channel}"
                }
                
                # 写入Supabase
                response = requests.post(
                    f"{supabase_url}/rest/v1/shipment_tracking",
                    headers={
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "apikey": supabase_key,
                        "Prefer": "return=minimal"
                    },
                    data=json.dumps(data_to_insert),
                    timeout=10
                )
                
                if response.status_code in [200, 201, 204]:
                    success_count += 1
                    print(f"✅ 同步成功: {shipment.tracking_number}")
                else:
                    error_count += 1
                    print(f"❌ 同步失败: {shipment.tracking_number} - {response.text}")
                    
            except Exception as e:
                error_count += 1
                print(f"🔥 同步异常: {shipment.tracking_number} - {str(e)}")
        
        flash(f"基本运单同步完成！成功: {success_count}, 失败: {error_count}", "success")
        
    except Exception as e:
        flash(f"同步过程出错: {str(e)}", "danger")
    
    return redirect(url_for("views.shipments"))


# =============== 修改：轨迹同步路由 ===============
@views.route("/admin/sync-tracking-details")
@login_required
def sync_tracking_details():
    """手动同步所有运单的轨迹信息（已优化去重）"""
    try:
        # 获取Supabase配置
        supabase_url = os.environ.get('SUPABASE_URL') or 'https://qxfzltryagnyiderbljf.supabase.co'
        supabase_key = os.environ.get('SUPABASE_KEY') or 'eyJhbGciOiJIUzI1NiIsInR5c極I6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF4ZnpsdHJ5YWdueWlkZXJibGpmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc3NTE4ODIsImV4cCI6MjA3MzMyNzg4Mn0.K90fwI3dwNJRXvIutvxhzzyVLjzgO7bfykAE26ZqGX4'
        
        print(f"🔄 开始同步轨迹信息（优化去重版）")
        
        # 获取所有有代理的运单
        shipments = Shipment.query.filter(Shipment.agent_id.isnot(None)).all()
        total_success = 0
        total_error = 0
        
        print(f"📦 找到 {len(shipments)} 个需要同步的运单")
        
        for shipment in shipments:
            try:
                agent = CarrierAgent.query.get(shipment.agent_id)
                if agent and agent.supports_api:
                    print(f"🔍 处理运单: {shipment.tracking_number}, 代理: {agent.name}")
                    
                    # 调用轨迹API
                    tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                    
                    print(f"📊 API返回: {len(tracks) if tracks else 0} 条轨迹, 错误: {error}")
                    
                    if tracks and not error:
                        # 使用优化后的同步函数
                        success_count, error_count = sync_tracking_to_supabase(shipment, tracks)
                        total_success += success_count
                        total_error += error_count
                        print(f"📊 运单 {shipment.tracking_number} 同步结果: 成功 {success_count}, 失败 {error_count}")
                    else:
                        print(f"⚠️ 无法获取轨迹: {error}")
                        total_error += 1
                else:
                    print(f"⏭️ 跳过运单 {shipment.tracking_number}: 代理不支持API")
                    total_error += 1
                        
            except Exception as e:
                total_error += 1
                print(f"🔥 处理 {shipment.tracking_number} 时出错: {str(e)}")
        
        print(f"🎯 同步完成: 成功 {total_success}, 失败 {total_error}")
        flash(f"轨迹同步完成！成功: {total_success}, 失败: {total_error}", "success")
        
    except Exception as e:
        print(f"💥 同步过程严重错误: {str(e)}")
        flash(f"轨迹同步过程出错: {str(e)}", "danger")
    
    return redirect(url_for("views.shipments"))

# -------------------------------
# 一键刷新物流轨迹
# -------------------------------
@views.route("/admin/refresh-tracking")
@login_required
def refresh_tracking():
    """严格内存防护的刷新函数"""
    try:
        import gc
        import time
        
        # 内存防护：只获取最近1天的3个运单
        one_day_ago = datetime.utcnow() - timedelta(days=1)
        shipments = Shipment.query.filter(
            Shipment.agent_id.isnot(None),
            Shipment.created_at >= one_day_ago
        ).limit(3).all()  # 限制最多3个运单
        
        updated_count = 0
        error_count = 0
        total_count = len(shipments)
        
        print(f"🔄 开始刷新 {total_count} 个运单 (严格内存防护)")
        
        for i, shipment in enumerate(shipments, 1):
            try:
                print(f"📦 处理 {i}/{total_count}: {shipment.tracking_number}")
                
                agent = CarrierAgent.query.get(shipment.agent_id)
                if agent and agent.supports_api:
                    # 调用轨迹API
                    tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                    
                    if tracks and not error:
                        # 简化同步
                        success_count = simple_sync_tracking(shipment, tracks)
                        
                        if success_count > 0:
                            updated_count += 1
                            print(f"✅ 运单更新成功")
                        else:
                            print(f"ℹ️ 运单无新轨迹")
                    else:
                        error_count += 1
                        print(f"❌ 获取轨迹失败")
                else:
                    error_count += 1
                    print(f"⏭️ 代理不支持")
                
                # 内存防护：处理完每个运单后强制清理
                gc.collect()
                
                # 内存防护：增加延迟，避免频繁请求
                if i < total_count:  # 最后一个不需要延迟
                    time.sleep(5)  # 更长的延迟
                    
            except Exception as e:
                error_count += 1
                print(f"🔥 运单处理出错")
                gc.collect()  # 出错时也清理内存
        
        flash(f"刷新完成！成功: {updated_count}/{total_count}, 失败: {error_count}", "success")
        
    except Exception as e:
        flash(f"刷新过程出错", "danger")
    
    return redirect(url_for("views.shipments"))


@views.route("/shipments/<int:shipment_id>/refresh")
@login_required
def refresh_single_tracking(shipment_id):
    """刷新单个运单的物流轨迹"""
    try:
        shipment = Shipment.query.get_or_404(shipment_id)
        
        if not shipment.agent_id:
            flash("该运单没有配置物流代理", "warning")
            return redirect(url_for("views.shipments"))
        
        agent = CarrierAgent.query.get(shipment.agent_id)
        if not agent or not agent.supports_api:
            flash("该运单的代理不支持API抓取", "warning")
            return redirect(url_for("views.shipments"))
        
        print(f"🔄 刷新单个运单: {shipment.tracking_number}")
        
        # 调用轨迹API获取最新数据
        tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
        
        if tracks and not error:
            # 同步到Supabase
            success_count = simple_sync_tracking(shipment, tracks)
            
            if success_count > 0:
                flash(f"运单 {shipment.tracking_number} 更新成功，新增 {success_count} 条轨迹", "success")
            else:
                flash(f"运单 {shipment.tracking_number} 暂无新轨迹", "info")
        else:
            flash(f"获取运单 {shipment.tracking_number} 轨迹失败: {error}", "danger")
            
    except Exception as e:
        flash(f"刷新过程出错: {str(e)}", "danger")
        import traceback
        traceback.print_exc()
    
    return redirect(url_for("views.shipments"))


def simple_sync_tracking(shipment, tracks):
    """修复环境变量+内存溢出防护"""
    try:
        import requests
        import json
        import os
        import gc  # 添加垃圾回收
        
        # 使用正确的环境变量名称
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_ANON_KEY')
        
        print(f"🔧 环境变量检查:")
        print(f"   SUPABASE_URL: {supabase_url is not None}")
        print(f"   SUPABASE_ANON_KEY: {supabase_key is not None}")
        
        if not supabase_url or not supabase_key:
            print("❌ Supabase配置缺失 - 跳过该运单")
            return 0
        
        success_count = 0
        
        # 内存防护1：限制处理轨迹数量
        recent_tracks = tracks[:1] if tracks else []  # 只处理1条，避免内存溢出
        
        print(f"📦 处理 {len(recent_tracks)} 条轨迹 (严格限制数量)")
        
        for i, track in enumerate(recent_tracks):
            try:
                # 内存防护2：简化数据处理
                description = track.get('description') or track.get('info') or track.get('status') or '无描述'
                description = str(description)[:30]  # 更短的长度限制
                
                event_time = track.get('time') or '2025-01-01T00:00:00Z'
                location = track.get('location') or ''
                
                # 内存防护3：简化数据结构
                track_data = {
                    "tracking_number": shipment.tracking_number,
                    "event_time": event_time,
                    "location": location,
                    "description": description
                }
                
                print(f"📝 写入 {i+1}/{len(recent_tracks)}: {description}")
                
                # 内存防护4：使用更短的超时和简化的请求
                response = requests.post(
                    f"{supabase_url}/rest/v1/shipment_tracking_details",
                    headers={
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json", 
                        "apikey": supabase_key,
                        "Prefer": "return=minimal"
                    },
                    data=json.dumps(track_data),
                    timeout=3  # 更短的超时
                )
                
                # 内存防护5：简化响应处理
                if response.status_code in [200, 201, 204, 409]:
                    success_count += 1
                    print(f"✅ 写入成功")
                else:
                    print(f"⚠️ 写入异常: {response.status_code}")
                
                # 内存防护6：立即清理临时变量
                del track_data, description, event_time, location
                    
            except Exception as e:
                print(f"❌ 单条写入失败")
        
        # 内存防护7：强制垃圾回收
        gc.collect()
        
        print(f"🎯 完成: {success_count}/{len(recent_tracks)} 成功")
        return success_count
        
    except Exception as e:
        print(f"💥 写入过程出错")
        return 0
    
# -------------------------------
# 自动同步功能
# -------------------------------

def complete_sync_tracking(shipment, tracks):
    """完整同步所有物流轨迹 - 修复版本"""
    try:
        if not tracks:
            return 0
            
        print(f"📝 开始处理 {len(tracks)} 条轨迹数据")
        
        # 获取现有的轨迹时间戳，避免重复
        existing_timestamps = set()
        for existing_track in shipment.tracks:
            # 使用完整的时间戳格式进行比较
            time_key = existing_track.track_time.strftime('%Y-%m-%d %H:%M:%S')
            existing_timestamps.add(time_key)
            print(f"🕒 现有轨迹: {time_key} - {existing_track.track_description}")
        
        added_count = 0
        # 按时间顺序处理轨迹（从早到晚）
        sorted_tracks = sorted(tracks, key=lambda x: x.get('track_time'))
        
        for track_data in sorted_tracks:
            track_time = track_data.get('track_time')
            track_description = track_data.get('track_description', '')
            location = track_data.get('location', '')
            
            if not track_time:
                continue
                
            # 标准化时间格式进行比较
            time_key = track_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # 检查是否已存在相同时间的轨迹
            if time_key in existing_timestamps:
                print(f"⏭️ 跳过已存在轨迹: {time_key}")
                continue
                
            print(f"➕ 添加新轨迹: {time_key} - {track_description}")
            
            # 创建新的轨迹记录
            new_track = Track(
                shipment_id=shipment.id,
                track_time=track_time,
                track_description=track_description,
                location=location
            )
            
            db.session.add(new_track)
            added_count += 1
            existing_timestamps.add(time_key)
            
        if added_count > 0:
            db.session.commit()
            print(f"✅ 成功添加了 {added_count} 条新轨迹到数据库")
        else:
            print("ℹ️ 没有发现新的轨迹需要添加")
            
        return added_count
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ 同步轨迹失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0


@views.route("/admin/refresh-full-history/<int:shipment_id>")
@login_required
def refresh_full_history(shipment_id):
    """强制刷新完整历史轨迹 - 解决历史数据缺失问题"""
    try:
        shipment = Shipment.query.get_or_404(shipment_id)
        
        if not shipment.agent_id:
            flash("该运单没有关联代理，无法刷新", "warning")
            return redirect(url_for("views.shipments"))
        
        agent = CarrierAgent.query.get(shipment.agent_id)
        if not agent:
            flash("找不到对应的代理", "warning")
            return redirect(url_for("views.shipments"))
        
        print(f"🔄 开始强制刷新完整历史轨迹: {shipment.tracking_number}")
        
        # 获取完整轨迹数据
        tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
        if tracks:
            print(f"📦 从API获取到 {len(tracks)} 条轨迹")
            
            # 显示所有获取到的轨迹
            for i, track in enumerate(tracks):
                time_str = track.get('track_time').strftime('%Y-%m-%d %H:%M:%S') if track.get('track_time') else '未知时间'
                print(f"  {i+1}. {time_str} - {track.get('location', '')} - {track.get('track_description', '')}")
            
            # 使用完整同步函数
            success_count = complete_sync_tracking(shipment, tracks)
            if success_count > 0:
                flash(f"✅ 完整历史轨迹刷新成功！添加了 {success_count} 条轨迹", "success")
                print(f"✅ 完整历史轨迹刷新成功: {shipment.tracking_number}")
            else:
                flash("没有发现新的轨迹信息", "info")
        else:
            flash(f"获取轨迹失败: {error}", "danger")
            print(f"❌ 获取轨迹失败: {error}")
            
    except Exception as e:
        error_msg = f"刷新完整历史失败: {str(e)}"
        flash(error_msg, "danger")
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()
    
    return redirect(url_for("views.shipments"))


@views.route("/admin/auto-sync-single/<int:shipment_id>")
@login_required
def auto_sync_single(shipment_id):
    """同步单个运单 - 使用完整同步"""
    try:
        shipment = Shipment.query.get_or_404(shipment_id)
        
        if not shipment.agent_id:
            flash("该运单没有关联代理，无法同步", "warning")
            return redirect(url_for("views.shipments"))
        
        agent = CarrierAgent.query.get(shipment.agent_id)
        if not agent or not agent.supports_api:
            flash("该代理不支持API同步", "warning")
            return redirect(url_for("views.shipments"))
        
        print(f"📦 开始同步单个运单: {shipment.tracking_number}")
        
        tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
        if tracks and not error:
            print(f"📦 获取到 {len(tracks)} 条轨迹数据")
            
            # 使用完整的轨迹同步函数
            success_count = complete_sync_tracking(shipment, tracks)
            if success_count > 0:
                flash(f"✅ 运单同步成功！添加了 {success_count} 条轨迹", "success")
                print(f"✅ 单个运单同步成功: {shipment.tracking_number}")
            else:
                flash("没有发现新的轨迹信息", "info")
        else:
            flash(f"同步失败: {error}", "danger")
            print(f"❌ 同步失败: {error}")
            
    except Exception as e:
        error_msg = f"运单同步失败: {str(e)}"
        flash(error_msg, "danger")
        print(f"❌ {error_msg}")
        import traceback
        traceback.print_exc()
    
    return redirect(url_for("views.shipments"))


@views.route("/admin/auto-sync-all-safe")
@login_required
def auto_sync_all_safe():
    """安全版本的全量同步 - 极低内存占用"""
    try:
        # 使用流式处理，避免一次性加载所有数据
        page = 1
        page_size = 5  # 减少每批数量
        total_updated = 0
        total_processed = 0
        max_process = 30  # 最大处理数量
        
        while total_processed < max_process:
            # 使用分页查询，只获取必要字段
            shipments_pagination = Shipment.query.filter(
                Shipment.agent_id.isnot(None)
            ).paginate(page=page, per_page=page_size, error_out=False)
            
            if not shipments_pagination.items:
                break
                
            print(f"🔄 处理第 {page} 批运单，共 {len(shipments_pagination.items)} 个")
            
            for shipment in shipments_pagination.items:
                try:
                    if total_processed >= max_process:
                        break
                        
                    total_processed += 1
                    print(f"📦 处理进度: {total_processed}/{max_process} - {shipment.tracking_number}")
                    
                    # 极简内存监控
                    try:
                        import psutil
                        memory_usage = psutil.virtual_memory().percent
                        if memory_usage > 70:  # 更严格的内存限制
                            print(f"⚠️ 内存使用较高 ({memory_usage}%)，提前结束")
                            flash(f"内存使用较高，已安全同步 {total_updated}/{total_processed} 个运单", "warning")
                            return redirect(url_for("views.shipments"))
                    except ImportError:
                        pass
                    
                    # 处理单个运单
                    agent = CarrierAgent.query.get(shipment.agent_id)
                    if agent and agent.supports_api:
                        tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                        if tracks and not error:
                            success_count = complete_sync_tracking(shipment, tracks)
                            if success_count > 0:
                                total_updated += 1
                                print(f"✅ 运单同步成功: {shipment.tracking_number}")
                    
                    # 立即释放内存
                    import gc
                    gc.collect()
                    
                    # 更长的延迟，减少服务器压力
                    time.sleep(5)
                    
                except Exception as e:
                    print(f"❌ 运单同步失败: {shipment.tracking_number} - {str(e)}")
                    continue
            
            page += 1
        
        flash(f"安全同步完成！更新 {total_updated}/{total_processed} 个运单", "success")
        
    except Exception as e:
        flash(f"同步过程出错: {str(e)}", "danger")
    
    return redirect(url_for("views.shipments"))


@views.route("/admin/auto-sync-all")
@login_required
def auto_sync_all():
    """自动同步所有运单 - 优化内存版本"""
    try:
        # 分批处理，避免一次性加载所有数据
        page = 1
        page_size = 10  # 减少每批数量
        total_updated = 0
        total_processed = 0
        
        while True:
            # 分批查询运单
            shipments = Shipment.query.filter(
                Shipment.agent_id.isnot(None)
            ).paginate(page=page, per_page=page_size, error_out=False)
            
            if not shipments.items:
                break
                
            print(f"🔄 处理第 {page} 批运单，共 {len(shipments.items)} 个")
            
            batch_updated = 0
            for i, shipment in enumerate(shipments.items, 1):
                try:
                    total_processed += 1
                    print(f"📦 总进度: {total_processed} - {shipment.tracking_number}")
                    
                    # 内存监控
                    try:
                        import psutil
                        memory_usage = psutil.virtual_memory().percent
                        
                        if memory_usage > 80:  # 降低阈值
                            print(f"⚠️ 内存使用过高 ({memory_usage}%)，停止同步")
                            flash(f"内存使用过高，已同步 {total_updated}/{total_processed} 个运单", "warning")
                            return redirect(url_for("views.shipments"))
                    except ImportError:
                        # 如果没有安装psutil，跳过内存检查
                        pass
                    
                    agent = CarrierAgent.query.get(shipment.agent_id)
                    if agent and agent.supports_api:
                        tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                        if tracks and not error:
                            # 使用完整同步函数
                            success_count = complete_sync_tracking(shipment, tracks)
                            if success_count > 0:
                                total_updated += 1
                                batch_updated += 1
                                print(f"✅ 运单同步成功: {shipment.tracking_number}")
                    
                    # 增加延迟
                    time.sleep(4)
                    
                    # 立即垃圾回收
                    import gc
                    gc.collect()
                        
                except Exception as e:
                    print(f"❌ 运单同步失败: {shipment.tracking_number} - {str(e)}")
                    continue
            
            print(f"✅ 第 {page} 批完成，更新了 {batch_updated} 个运单")
            page += 1
            
            # 限制总处理数量，防止无限循环
            if total_processed >= 50:  # 减少最大处理数量
                print("⚠️ 达到最大处理限制 (50个运单)")
                break
        
        flash(f"自动同步完成！更新 {total_updated}/{total_processed} 个运单", "success")
        
    except Exception as e:
        flash(f"自动同步失败: {str(e)}", "danger")
    
    return redirect(url_for("views.shipments"))


@views.route("/admin/auto-sync-recent")
@login_required
def auto_sync_recent():
    """手动触发最近运单同步 - 优化内存版本"""
    try:
        # 同步最近7天的运单，进一步限制数量
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        shipments = Shipment.query.filter(
            Shipment.agent_id.isnot(None),
            Shipment.created_at >= seven_days_ago
        ).limit(8).all()  # 减少到8个
        
        updated_count = 0
        total_count = len(shipments)
        
        print(f"🔄 开始同步最近 {total_count} 个运单")
        
        for i, shipment in enumerate(shipments, 1):
            try:
                print(f"📦 同步进度: {i}/{total_count} - {shipment.tracking_number}")
                
                agent = CarrierAgent.query.get(shipment.agent_id)
                if agent and agent.supports_api:
                    # 添加内存监控
                    try:
                        import psutil
                        memory_usage = psutil.virtual_memory().percent
                        
                        if memory_usage > 80:  # 降低阈值
                            print(f"⚠️ 内存使用过高 ({memory_usage}%)，停止同步")
                            flash(f"内存使用过高，已同步 {updated_count}/{i-1} 个运单", "warning")
                            break
                    except ImportError:
                        # 如果没有安装psutil，跳过内存检查
                        pass
                    
                    tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                    if tracks and not error:
                        # 使用完整同步函数
                        success_count = complete_sync_tracking(shipment, tracks)
                        if success_count > 0:
                            updated_count += 1
                            print(f"✅ 最近运单同步成功: {shipment.tracking_number}")
                
                # 增加延迟，减少服务器压力
                time.sleep(4)
                
                # 立即垃圾回收
                import gc
                gc.collect()
                
            except Exception as e:
                print(f"❌ 最近运单同步失败: {shipment.tracking_number} - {str(e)}")
                # 继续处理下一个运单，不中断整个流程
        
        flash(f"最近运单同步完成！更新 {updated_count}/{total_count} 个运单", "success")
        
    except Exception as e:
        flash(f"最近运单同步失败: {str(e)}", "danger")
    
    return redirect(url_for("views.shipments"))