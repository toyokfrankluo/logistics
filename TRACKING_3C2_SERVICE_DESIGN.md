# 3C-2B 独立查询服务（尚未接入路由）

本阶段仅增加 tracking 服务模块、测试和本说明。app.py、views.py、权限、CSRF、模型、前端与3B接口保持原样。当前没有真实传输实现、生产配置开关或数据库仓储。

## 使用与职责

- `resolve_query(QueryRequest, ReadOnlyRepository) -> QueryPlan`：按本地主键或客户单号二选一解析；客户单号多票阻断。公共计划先第三方再关联代理，后台仅关联代理；不猜环境货代、不接受跨代理覆盖。
- `query_tracking(QueryPlan, ResponseProvider) -> QueryOutcome`：只调用注入的fetch；响应只传给现有3B适配器。无数据库、网络客户端、重试、日志、缓存、同步或持久化。传输实现应将自身超时异常转换为标准库TimeoutError，其他异常安全归为transport_or_adapter，不回显正文或异常文字。
- `present_legacy(QueryOutcome, contract) -> LegacyPresentation`：支持public_json、public_html结果字典、backend结果字典；不生成整个HTML页面。不能还原时compatible=False，payload=None并列明原因。调用方必须先检查compatible，不得忽略它。

ports.py只声明协议。测试中的MemoryRepository和FakeResponses为内存实现；没有生产HTTP实现。audience仅选择策略，不表示用户已获授权；未来路由仍负责现有登录、管理员、POST及CSRF校验。

## 身份与启用门槛

ShipmentSnapshot.local_id对应Shipment.id；customer_number、provider_number、third_party_number互不替代。ManualEvent.record_id为手工记录身份，手工事件的外键由仓储限定到该运单，不能传错票。

RTB56/TXFBA使用客户单号；NextSLS仅代理单号；17Track仅第三方单号。generic即使verified=True也阻断，因为其请求协议尚未确定。Source.verified默认False；测试设True仅代表虚构已批准策略，不表示真实协议已证实。供应商类型明确给定，不分析URL。

执行阶段再次校验来源和单号，不能靠手工构造Attempt绕过规则。Source配置及只读仓储属于可信注入边界，不可由未认证的请求正文直接构造。

## 状态与来源

success/empty/error/unverified来自适配器；blocked用于身份、协议、停用或缺单号；not_requested用于纯本地模式或无外部来源。手工记录与每个SourceOutcome独立保留，不因自动失败而丢弃。无外部来源时整体success/empty仅表示本地结果，sources中external=not_requested。

公共第三方明确error后才调用关联代理；success、empty、unverified终止回退。配置blocked不触发回退，防止协议或授权阻断被绕过。这是保守安全边界，未来接入前需单独审核其与旧路由的差异。回退成功保留首个来源失败诊断。没有配置的第三方来源不会仅凭单号创建请求。

事件保持来源内顺序、长描述、重复自动事件、unknown状态和未知时间。手工仅消除重复加入的同一record_id，不按内容去重；不同ID的同内容事件保留。服务不做全来源时间排序或状态推导，不以接收时间补事件时间。

手工时间按仓储提供的原值保留；当前模型默认时间的历史来源不可追溯，不能宣称为验证后的发生时间。3B供应商协议、epoch单位、状态/ID映射待确认项完整保留，不被verified策略标志抹去。

## 兼容范围与明确阻断

已支持RTB56/TXFBA正常响应的公共JSON字段/类型、公共文本分隔与后台逐行文本；后台支持手工分钟时间和“暂无轨迹”。公共JSON成功为order_id/error/tracks，tracks为字符串。public_html返回供旧模板消费的error/tracks字典，不更改模板。

以下情况明确incompatibility，等待独立决策，不伪造结果：

1. unverified没有旧成功语义。
2. 公共手工轨迹选择/失败时展示历史规则尚不能统一。
3. 公共empty依赖供应商cnmessage，3B已丢弃，不能无损还原。
4. NextSLS原始JSON、17Track格式及原始API信封不能从标准事件反建。
5. error/blocked的旧错误文字需要逐入口批准映射；内部错误类别不能假冒旧文本。因此本阶段失败结果不输出伪兼容payload，旧失败JSON结构待后续批准映射后支持。
6. 手工分钟时间无法可靠取得时，不补时间。

这不是对全部旧结果的兼容声明。来源成功但存在先前失败诊断时，诊断仍保留于Outcome，旧成功响应不显示失败回退过程，与原公共回退行为一致。

## 测试及后续切换

所有新增测试为虚构数据；验证单号歧义、NextSLS缺号、停用/未验证来源零请求、公共/后台来源顺序、回退恰好两次、空结果不回退、各失败类别、未知时间/状态、重复/长描述及兼容阻断。子进程确认不导入业务运行时，执行守卫阻断socket/SQLite/文件IO。

原有测试仍由既有隔离环境使用临时测试数据库；新增服务测试本身不连接任何数据库。

下一阶段先复核以上阻断与来源策略，再实施默认legacy、按入口和来源控制的开关。shadow必须复用同一响应，不重复请求。建议先后台RTB56/TXFBA，公共入口其次，原始API及协议不明路径最后。真实调用、真实影子、同步写入均不在本授权范围。

回滚仅revert本轮新增文件提交，不reset现有工作区。服务尚未接路由，无数据库回滚需求。开始前已有tracked差异备份于/tmp/logistics-3c2b-before.patch；原有未提交文件未覆盖。

最终验证：Python 3.11.18，全量217项通过（原有173 + 新增44），0失败、0错误、0跳过。已有业务文件差异与本轮开始前补丁逐字节一致，git diff --check通过。旧代码仍有SQLAlchemy Query.get弃用提示，本阶段未修改。
