import requests
import json

url = "http://ywsl.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8"
appToken = "dfaf5c6ba49d58d8c3644671056cfb3b"
appKey = "4a1756eb968cd85f63b8ab3047e3bebf4a1756eb968cd85f63b8ab3047e3bebf"

tracking_number = "FBA190507RY7"

payload = {
    "appToken": appToken,
    "appKey": appKey,
    "serviceMethod": "gettrack",
    "paramsJson": json.dumps({"tracking_number": tracking_number}, ensure_ascii=False)
}

headers = {"Content-Type": "application/x-www-form-urlencoded"}

r = requests.post(url, headers=headers, data=payload)

print("状态码:", r.status_code)
print("返回内容:")
print(r.text)