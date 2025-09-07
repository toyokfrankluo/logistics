import requests

class CarrierAgent:
    """模拟你的代理对象"""
    def __init__(self, name, api_url, app_key=None, app_token=None, supports_api=True):
        self.name = name
        self.api_url = api_url
        self.app_key = app_key
        self.app_token = app_token
        self.supports_api = supports_api


def fetch_tracking_from_api(agent: CarrierAgent, tracking_number: str):
    """
    占位的 API 抓取逻辑
    """
    if not agent or not agent.api_url or not agent.supports_api:
        return None, "代理不支持 API 抓取"

    try:
        # 这里用 GET 请求测试（你可以改成 POST）
        resp = requests.get(agent.api_url, params={
            "appKey": agent.app_key or "demoKey",
            "appToken": agent.app_token or "demoToken",
            "tracking_number": tracking_number
        }, timeout=5)

        if resp.status_code == 200:
            try:
                data = resp.json()
                return data.get("tracks", "返回 JSON，但没有 tracks 字段"), None
            except Exception:
                return resp.text, None
        else:
            return None, f"API返回错误 {resp.status_code}"

    except Exception as e:
        return None, f"API请求失败: {str(e)}"


if __name__ == "__main__":
    # 你可以替换为真实的测试 API 地址
    agent = CarrierAgent(
        name="测试代理",
        api_url="https://httpbin.org/get",  # httpbin 是一个测试服务，可以返回你发过去的参数
        app_key="abc123",
        app_token="xyz789"
    )

    tracks, error = fetch_tracking_from_api(agent, "ABC123456")

    print("=== 测试结果 ===")
    if error:
        print("错误:", error)
    else:
        print("轨迹:", tracks)