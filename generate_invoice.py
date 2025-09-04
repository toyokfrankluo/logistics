from openpyxl import Workbook

# 模拟订单
orders = [
    {"date": "2025-08-04", "order_no": "FBA18ZQFOSM", "service_no": "FBA18ZQFOSM",
     "qty": 3, "type": "WPX", "weight": 46, "destination": "美国(GYR3)",
     "channel": "美中卡派", "fee": 299, "summary": "GYR3 单价4.5 产品附加2"},
]

# 模拟银行信息
bank_info = {
    "开户行": "招商银行深圳梅林支行",
    "户名": "罗泽",
    "账号": "6214837835366331"
}

def export_invoice(customer_name, orders, bank_info, filename="账单.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "账单"

    headers = ["序号", "日期", "订单号", "服务商单号", "件数", "类型", "计费重/KG", "目的地", "运输渠道", "合计费用", "账单摘要"]
    ws.append(headers)

    total_fee = 0
    for idx, order in enumerate(orders, start=1):
        ws.append([
            idx, order["date"], order["order_no"], order["service_no"],
            order["qty"], order["type"], order["weight"], order["destination"],
            order["channel"], order["fee"], order["summary"]
        ])
        total_fee += order["fee"]

    ws.append([])
    ws.append(["客户名称", customer_name])
    ws.append(["总票数", len(orders)])
    ws.append(["总费用", total_fee])

    ws.append([])
    ws.append(["收款银行信息"])
    for k, v in bank_info.items():
        ws.append([k, v])

    wb.save(filename)
    print(f"✅ 已生成账单：{filename}")

# 测试
export_invoice("广西粤好", orders, bank_info, "客户账单.xlsx")