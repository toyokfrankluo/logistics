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
    """一键刷新所有运单的物流轨迹 - 智能去重版本"""
    try:
        # 获取最近30天的运单，避免处理过多历史数据
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        shipments = Shipment.query.filter(
            Shipment.agent_id.isnot(None),
            Shipment.created_at >= thirty_days_ago
        ).all()
        
        updated_count = 0
        error_count = 0
        total_count = len(shipments)
        
        print(f"🔄 开始智能刷新 {total_count} 个运单的物流轨迹")
        
        for i, shipment in enumerate(shipments, 1):
            try:
                print(f"📦 处理进度: {i}/{total_count} - {shipment.tracking_number}")
                
                agent = CarrierAgent.query.get(shipment.agent_id)
                if agent and agent.supports_api:
                    # 调用轨迹API获取最新数据
                    tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                    
                    if tracks and not error:
                        # 智能同步到Supabase（带去重）
                        success_count = simple_sync_tracking(shipment, tracks)
                        
                        if success_count > 0:
                            updated_count += 1
                            print(f"✅ 运单 {shipment.tracking_number} 更新成功，新增 {success_count} 条轨迹")
                        else:
                            print(f"ℹ️ 运单 {shipment.tracking_number} 无新轨迹")
                    else:
                        error_count += 1
                        print(f"❌ 运单 {shipment.tracking_number} 获取轨迹失败: {error}")
                else:
                    error_count += 1
                    print(f"⏭️ 跳过运单 {shipment.tracking_number}: 代理不支持API")
                
                # 短暂延迟，避免请求过于频繁
                time.sleep(1)
                    
            except Exception as e:
                error_count += 1
                print(f"🔥 刷新运单 {shipment.tracking_number} 时出错: {str(e)}")
        
        flash(f"轨迹刷新完成！成功更新: {updated_count}/{total_count}, 失败: {error_count}", "success")
        
    except Exception as e:
        flash(f"刷新过程出错: {str(e)}", "danger")
        import traceback
        traceback.print_exc()
    
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
    """智能写入轨迹到Supabase - 严格去重版本"""
    try:
        import requests
        import json
        import os
        from datetime import datetime
        
        supabase_url = os.environ.get('SUPABASE_URL')
        supabase_key = os.environ.get('SUPABASE_KEY')
        
        if not supabase_url or not supabase_key:
            print("❌ Supabase配置缺失")
            return 0
        
        success_count = 0
        duplicate_count = 0
        
        print(f"📦 准备处理 {len(tracks)} 条轨迹")
        
        # 严格去重：基于运单号+描述（完全忽略时间和位置，与数据库保持一致）
        unique_tracks = {}
        for track in tracks:
            description = track.get('description', track.get('info', track.get('status', ''))).strip()
            
            # 创建唯一标识符（只基于运单号和描述，忽略时间和位置）
            unique_key = f"{shipment.tracking_number}_{description}"
            
            if unique_key not in unique_tracks:
                unique_tracks[unique_key] = track
            else:
                print(f"⏭️ 跳过重复轨迹: {description[:40]}...")
                duplicate_count += 1
        
        print(f"🔍 严格去重后剩余 {len(unique_tracks)} 条唯一轨迹")
        
        # 写入Supabase
        for track_key, track in unique_tracks.items():
            try:
                # 标准化时间格式
                event_time = track.get('time', '')
                if not event_time:
                    event_time = datetime.utcnow().isoformat()
                elif " " in event_time and "T" not in event_time:
                    # 如果是 "2025-09-18 09:07:31" 格式，转换为ISO格式
                    try:
                        dt = datetime.strptime(event_time, "%Y-%m-%d %H:%M:%S")
                        event_time = dt.isoformat()
                    except:
                        event_time = datetime.utcnow().isoformat()
                
                description = track.get('description', track.get('info', track.get('status', ''))).strip()
                location = track.get('location', '').strip()
                
                track_data = {
                    "tracking_number": shipment.tracking_number,
                    "event_time": event_time,
                    "location": location,
                    "description": description
                }
                
                print(f"📝 写入: {description[:40]}...")
                
                # 尝试写入Supabase
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
                    print(f"✅ 写入成功")
                elif response.status_code == 409:
                    duplicate_count += 1
                    print(f"⏭️ 数据库层面跳过重复")
                else:
                    print(f"⚠️ 写入异常: {response.status_code}")
                    
            except Exception as e:
                print(f"❌ 写入失败: {str(e)}")
        
        print(f"🎯 最终结果: 成功 {success_count} 条, 跳过 {duplicate_count} 条重复")
        return success_count
        
    except Exception as e:
        print(f"💥 写入过程出错: {str(e)}")
        return 0