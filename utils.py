from openpyxl import Workbook

def export_invoice(company_info, customer_name, orders, bank_info, filename="账单.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "账单"

    # 顶部公司信息
    ws.append([company_info["公司名称"]])
    ws.append([f"地址: {company_info['地址']}"])
    ws.append([f"电话: {company_info['电话']}"])
    ws.append([])

    # 表头
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
    return filename