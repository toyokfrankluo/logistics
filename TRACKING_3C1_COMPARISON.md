# 3C-1：离线新旧结果对比与切换候选方案

仅新增 comparison 包、对比测试及本报告；未改变业务调用链、模型、权限、CSRF、模板或旧函数。输入全部虚构，结果不能证明真实供应商协议正确。

## 如何复现

`/tmp/logistics-dependency-check/bin/python -B -m comparison`

输出 JSON 到 stdout，不自动保存文件。comparison.runner 从当前 app.py/views.py 以 AST 提取指定的实际旧函数，在独立命名空间执行；不导入业务模块。运单/代理查询只用内存只读替身，HTTP post 是返回同一虚构响应的函数。没有数据库会话、真实 HTTP 客户端、接收时间或持久保存动作。每次创建独立空缓存，不污染现有进程。旧日志被捕获丢弃。

范围：public=call_gettrack/call_17track + format_tracks_from_data；backend=fetch_tracking_from_api/fetch_17track_tracking。它不是整个 Flask 路由执行器；路由、权限、手工轨迹合并、缓存行为仍由3A和已有回归覆盖。测试对SQLite连接、socket连接、文件写入设置拒绝守卫，并在独立子进程确认没有导入 app/views/Flask/SQLAlchemy/Requests。

## 比较口径

逐项记录旧事件数量、原始时间、事件顺序、地点、完整描述、旧错误文字/异常、旧结果展示文本，以及新查询状态、结构化错误、时间精度/UTC/本地时间/待确认项。新事件状态保持unknown，unverified不提升为success。

旧函数没有统一查询状态：no_explicit_error仅表示没有显式error，绝不等同可靠成功。旧公共NextSLS返回原始JSON、后台17Track返回字符串，因此结构化事件数量是null（不可提取），不是0；此时各字段比较也是null。顺序通过有序事件列表比较，不擅自排序或去重。原始时间不同不直接等于发生时刻不同，必须另审时区与格式。

下表“状态/数量”只展示摘要；完整字段差异见命令输出。分类是建议，不授权自动修改现有入口。

| 虚构场景 | 旧公共：状态/数量 | 旧后台：状态/数量 | 新适配器：状态/数量 | 主要分类 |
|---|---|---|---|---|
| rtb56-success | no_explicit_error/1 | no_explicit_error/1 | success/1 | compatibility |
| txfba-success | no_explicit_error/1 | no_explicit_error/1 | success/1 | compatibility |
| multiple-order | no_explicit_error/2 | no_explicit_error/2 | success/2 | compatibility |
| duplicate-events | no_explicit_error/2 | no_explicit_error/2 | success/2 | compatibility |
| long-description | no_explicit_error/1 | no_explicit_error/1 | success/1 | compatibility |
| missing-time | no_explicit_error/1 | no_explicit_error/1 | success/1 | protocol_unconfirmed |
| empty | no_explicit_error/0 | no_explicit_error/0 | empty/0 | compatibility |
| business-zero-str | no_explicit_error/0 | no_explicit_error/0 | error/0 | old_defect |
| business-zero-int | no_explicit_error/0 | error/0 | error/0 | old_defect |
| http-error | no_explicit_error/1 | error/0 | error/0 | old_defect |
| invalid-json | no_explicit_error/不可提取 | error/0 | error/0 | old_defect |
| missing-description | no_explicit_error/1 | no_explicit_error/1 | error/0 | protocol_unconfirmed |
| nextsls-success | no_explicit_error/不可提取 | no_explicit_error/1 | success/1 | compatibility |
| nextsls-epoch | no_explicit_error/不可提取 | no_explicit_error/1 | success/1 | protocol_unconfirmed |
| 17track-success | no_explicit_error/1 | no_explicit_error/不可提取 | success/1 | compatibility |
| generic-unverified | no_explicit_error/不可提取 | no_explicit_error/1 | unverified/1 | protocol_unconfirmed |
| generic-explicit-error | no_explicit_error/不可提取 | no_explicit_error/1 | error/0 | old_defect |

## 差异处置清单

1. **确定旧问题 old_defect**：公共RTB分支不检查HTTP状态；无效JSON以原文展示；"0"为真的旧判断；通用接口先取tracks再检查错误码。新组件应拒绝失败，但HTTP返回码、error字段和前端提示如何改变仍须批准，不能一并暗改。
2. **兼容行为 compatibility**：供应商信封、公共JSON的tracks文本/错误时空列表、后台文本格式、NextSLS原始JSON展示、17Track字符串展示。3C-2必须以兼容呈现层保留，或明确版本化变更；不能直接返回QueryResult替代旧JSON。
3. **应保留的数据行为**：事件输入顺序、重复事件、完整长描述与地点。两者在已知RTB/TXFBA正常样例一致；重复不等于可自动删除，去重属于后续独立规则。
4. **协议不明 protocol_unconfirmed**：无时区时间、缺时间/缺描述、epoch单位、generic成功标志、状态码和事件ID。新结果保留raw/unknown/unverified。NextSLS旧后台用机器时区转换epoch，不能据输出字符串断言新UTC错误。
5. **缺字段不等于无轨迹**：新适配器将坏结构报schema错误，旧代码可能容忍、返回空或未显式错误；描述是否必需仍需协议确认，不擅自丢弃历史。
6. **混合错误与有效事件**：是否整次拒绝或允许部分事件，需要高推理设计；本轮保持3B的整次拒绝，未修改规则。

## 运单身份和选择规则核对

- 本地Shipment.id是业务主键；tracking_number是客户单号且当前无数据库唯一约束；Shipment.shipment_id是代理系统单号，ManualTrack.shipment_id则是本地外键。三者不得互换。
- 当前多处用tracking_number查询first，重复单号时可能选错票；本轮不读取业务库判断是否实际重复。
- 公共 /public_track、/public/track 先用third_party_tracking_number调用17Track，失败后按运单代理/环境货代回退。后台views.track只按关联代理查询，未实现同样17Track优先级。
- call_gettrack中显式agent_id可覆盖运单代理；有代理时优先代理，carrier参数并不保证生效。后台代理/客户过滤主要决定空输入时选哪些票，显式输入单号后仍按first和原关联代理查询。
- NextSLS缺系统单号：公共拒绝且不发请求；后台把客户单号作为shipment_id。已用只读替身实测，属于身份风险，不能在切换时偷偷选择一种。
- 停用代理：公共拒绝；后台抓取函数未校验is_active。已用测试记录。
- 通用代理：旧公共只要有Key/Token就使用serviceMethod/paramsJson格式；后台用appKey/appToken/tracking_number。相同来源名称不代表请求协议相同。
- provider选择仍靠URL子串；公共NextSLS判断包含sls即命中，后台更窄。新适配器provider须由明确配置选择，不应继续以宽泛子串猜测。

## 统一查询服务候选接口（仅设计）

`resolve_query(shipment_pk, audience, requested_source=None) -> QueryPlan`

QueryPlan明确记录本地主键、客户单号、代理单号、第三方单号、代理实例source_id、provider、允许的回退链与阻断原因。解析输入不能只传一串tracking_number。存在重复匹配或越权来源选择时不自动选first。

`query_tracking(plan, response_provider) -> QueryOutcome`

response_provider为可注入传输层。Outcome保留查询状态、自动事件、手工事件、来源、刷新诊断与待确认项；接收时间与事件时间分离。只读查询不写本地或Supabase。未来刷新写入是单独的管理员操作，不放进公共CSRF豁免接口。

`present_legacy(outcome, endpoint_contract) -> 旧响应结构`

呈现层承担接口兼容，但不得把unknown映射成签收，也不得将unverified伪装成功。若现有成功契约无法表达不确定性，必须先批准新字段或版本化接口。

## 3C-2安全切换方案

1. 先批准身份、provider/回退规则及本报告的语义改变清单，明确哪些旧输出继续兼容。
2. 将上述候选接口实现为可注入服务，默认开关关闭，不接自动持久化、不引入迁移。
3. 用同一份已获取响应做内存影子对比，不能为新旧两套逻辑各调用一次供应商；真实影子运行必须另行授权。日志仅写脱敏差异指标，不能写客户轨迹或响应正文。
4. 先接一个明确协议的入口/供应商，保留旧函数和呈现层；原146项及新增对比测试全部通过。获批语义改变需逐条更新旧契约测试，不要为全绿而批量改断言。
5. 检查公共/后台、三种角色、CSRF、停用代理、缺单号、HTTP错误、长描述、时间、重复事件；未明确协议的路径继续旧实现或明确阻断，不凭空映射。
6. 可按入口回退开关，清理受影响的进程缓存，回到旧调用链；由于此阶段无数据库写入，无需回滚数据库。旧代码/权限保持可用。

## 需 Astra 高推理决策

身份冲突及显式来源选择权限；跨来源合并与回退优先级；时区/epoch和缺时间排序；unknown/unverified如何进入旧接口；供应商修正/重复事件身份；部分成功与失败缓存；从查询发展到刷新写入时的事务和并发边界。供应商协议事实须有资料或经授权验证，模型推理不能替代证据。

## 验证与回滚

Python3.11.18。新增27项测试（17个固定语料场景 + 10项比较/隔离/身份规则测试），没有expectedFailure或跳过。运行全量：`/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v`。

本轮只新增comparison/四个文件、tests/test_tracking_comparison.py、本报告，共6文件；单独本地提交，原有未提交工作保持。回退本轮提交即可撤下对比工具，不回退整个开发分支。未推送或部署，未导入/运行旧初始化、自动刷新或重置脚本。

最终全量验证：173通过（原有146 + 新增27），0失败、0错误、0跳过。已有业务文件差异与3A前保存的补丁一致；git diff --check通过。
