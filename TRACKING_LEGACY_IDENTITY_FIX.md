# 3C-2C-D legacy后台运单身份修复

仅修改views.track、fetch_tracking_from_api、track.html显示标签及新增测试。公共查询、shadow、TrackingService、模型、权限、CSRF、供应商协议均未修改。

显式单号只在当前客户/代理筛选范围中匹配：零条返回“当前查询范围内未找到运单”，多条返回“当前查询范围内运单号不唯一，请缩小筛选范围”，两者均不调用供应商。唯一匹配保留Shipment对象。重复输入同一单号仅处理一次，避免同一记录重复请求。

空输入批量使用query.all()对象本身。同号但不同本地主键的记录分别处理，结果字典以Shipment.id为键，不相互覆盖；模板只显示tracking_number，不公开本地主键，正常唯一匹配文字保持原样。无法匹配的输入使用单独input:索引键，不与整数主键冲突。

fetch_tracking_from_api增加可选关键字selected_shipment；提供时先验证单号及关联代理一致，NextSLS使用此对象而非二次全局first。其他旧调用方未传该参数时保持旧逻辑；因此不能宣称全项目first已被消除。本轮/track的全部供应商调用都会传入对象。

NextSLS缺代理单号时使用客户单号的旧规则按授权保持。它仍是未经协议验证的风险，本轮未批准修复或接真实服务。

筛选不是客户级授权。当前用户体系未建立用户到客户的数据范围映射，本轮不扩大已有权限，也不提供租户隔离保证。并发修改/删除关联对象仍属后续事务快照设计范围。

测试使用现有隔离临时SQLite和虚构数据，供应商为mock。新增覆盖筛选冲突、跨客户/代理同号、歧义、批量主键与结果保留、NextSLS不二次查询及旧回退、helper代理不匹配、正常文本/次数、重复输入。

回滚：只revert本轮提交，勿reset --hard。旧未提交工作通过/tmp/logistics-identity-before.patch及/tmp/logistics-identity-before-views.py保留。本轮views.py与模板仅暂存相关hunk。

本地复现：/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_track_identity.py' -v
全量：/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_*.py'

最终结果：Python3.11.18，原有242项+新增13项=255项通过，0失败、0错误、0跳过。未改旧测试断言。已有SQLAlchemy Query.get弃用提示保留，git diff --check通过。
