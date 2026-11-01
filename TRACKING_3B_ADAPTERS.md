# 3B：独立响应适配器

本轮仅新增 tracking 包、tests/test_tracking_adapters.py 和本说明。现有 app.py、views.py、utils.py、数据库模型、权限、CSRF、模板与依赖没有修改；所有旧实现保留，不接入业务调用链。

## 使用

```python
from tracking import parse_response, QueryStatus
result = parse_response(
    'rtb56', 'agent:fictional', 200,
    '{"success":"1","data":[{"details":[{"track_description":"虚构轨迹"}]}]}'
)
assert result.status == QueryStatus.SUCCESS
assert result.events[0].time.occurred_at is None
```

只接受调用方提供的 HTTP 状态和 JSON 文本。组件不发送 HTTP 请求，不导入 Flask/SQLAlchemy/Requests，不读环境变量、文件或数据库。source_id 由调用方明确提供，代表代理/货代实例；不能只用协议名称区分不同代理。

## 模块

- types.py：不可变事件、时间、查询结果；查询状态 success/empty/error/unverified，错误类型 HTTP/JSON/业务/结构/待确认。
- time.py：保留原始时间，识别日期、分钟、秒、子秒；显式偏移或调用方明确提供的时区才能产生 UTC 时间。无时区字符串保留 local_time，occurred_at=None；日期不补零点。DST 重复/不存在时间不猜测。
- adapters.py：一个显式 provider 入口；RTB56 与 TXFBA 共用已存在的 details 解析规则，其他供应商各自提取事件。
- __init__.py：独立使用入口。

## 代码证据与支持范围

| provider | 支持格式 | 项目依据 |
|---|---|---|
| rtb56 / txfba | success，data[0].details，track_occur_date/location/description，英文描述备选 | views.py fetch_tracking_from_api；app.py call_gettrack/format_tracks_from_data |
| nextsls | status，data.shipment.traces，time/location/info；tracks 或列表 data 为待确认备选 | views.py fetch_tracking_from_api；app.py call_nextsls |
| 17track | status=200，data[0].track，time/location/description 或 info | app.py call_17track、views.py fetch_17track_tracking；这是现有实现的协议子集，不是官方 API 合规声明 |
| generic | tracks / data 列表 / result.list，time/happen_time/occur_date、location、description/info | views.py 通用解析与后台展示、app.py 备选解析；字段语义始终待确认 |

成功标志采用类型敏感白名单：RTB/TXFBA 为整数1或字符串"1"；NextSLS 为整数1/200、字符串"1"/"200"、布尔True（旧 helper 明确列出）；17Track 为整数200。通用接口识别 success=1/"1"、status=整数200、code=整数200，但标记协议待确认；缺这些标志的可解析事件返回 unverified，不视为成功。字符串"0"、整数0、False、浮点值不能因 Python 隐式相等或真假判断变成成功。

只有供应商本身的成功标志参与专用协议判断，不猜测其他同名字段含义。显式 error 优先；固定错误消息不回传供应商错误原文。HTTP 非200直接报错。JSON、结构或任意事件异常不返回部分成功。明确事件列表为空才是 empty；缺事件容器是 schema 错误。data 外层包含多个运单时拒绝，不静默只取第一票。适配器不去重、不排序、不改变状态、不截断描述。

## 待确认事项

所有结果均携带 supplier_protocol_not_verified、status_mapping_unconfirmed、external_event_id_mapping_unconfirmed。当前没有可信状态码或事件 ID 映射证据，因此状态一律 unknown，external_event_id=None，不能把任意 id/status 字段当作已确认语义，也不按描述推断签收。

NextSLS 数字时间按旧代码继承“Unix 秒”解释，0 是合法 epoch，而不是缺失时间；单位仍须供应商确认，不能自动猜毫秒。其他供应商数字时间保留 raw、绝对时间未知。无时区时间需要明确配置；不得使用 Mac/服务器默认时区。

描述为必需文本，缺失/错误类型返回 schema 错误；地点缺失允许空字符串。日志完全不输出响应；结果只保留映射字段，不保存原始信封或供应商错误文本。事件描述、原始时间本身仍可能含业务敏感信息，未来调用方不能因此随意打印整个结果。

本轮不实现网络传输、超时重试、请求签名、状态推导、去重、自动持久化或 Supabase。HTTP 状态由调用方提供；真实网络超时没有 JSON 响应，未来传输层应单独建模。

## 验证及回滚

Python 3.11.18；新增64项独立测试通过，包括五个供应商各10个场景，以及独立导入、无日志、时区、DST、时间精度、备选格式和未知状态。新测试的子进程验证导入不会加载 Flask、SQLAlchemy、Requests。

运行全部：`/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v`。

开始前已有修改原样保留，新增组件单独本地提交；反向撤销本轮提交即可回滚，不重置整个工作区。旧追踪回归基点为9f56671。没有生产调用链切换，所以撤回组件不会改变现有页面行为。

进入3C前：确认供应商成功标志/时间单位/时区/状态码/事件ID；确认generic是否允许未验证结果显示；批准哪些3A差异将改变；确认只读查询与刷新写入边界。数据库迁移和真实接口验证仍需单独授权。

最终全量结果：146通过（原有82 + 新增64），0失败、0错误、0跳过。现有业务修改与3A前保存的差异补丁一致；git diff --check 通过。
