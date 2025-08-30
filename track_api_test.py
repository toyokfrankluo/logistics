import requests
import json

url = "http://ywsl.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8"
appToken = "dfaf5c6ba49d58d8c3644671056cfb3b"
appKey = "4a1756eb968cd85f63b8ab3047e3bebf4a1756eb968cd85f63b8ab3047e3bebf"

def get_tracking(tracking_number: str):
    payload = {
        "appToken": appToken,
        "appKey": appKey,
        "serviceMethod": "gettrack",
        "paramsJson": json.dumps({"tracking_number": tracking_number}, ensure_ascii=False)
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    resp = requests.post(url, headers=headers, data=payload)
    result = resp.json()
    return result