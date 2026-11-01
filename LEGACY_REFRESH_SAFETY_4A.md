# 4A 旧刷新与同步安全修复

范围：views.py刷新/同步调用链、相关helper和新增测试。公共入口、数据库模型、TrackingService、shadow及任务调度不变。

## 身份及保护

所有已持有Shipment的fetch_tracking_from_api调用改走_refresh_query，显式传selected_shipment及safe_errors=True。供应商凭据来自该运单关联代理，NextSLS参数使用该对象，不二次按客户单号选票。helper的无显式运单旧调用保留first；/track已有显式对象但不启用safe_errors，旧输出保持。

_refresh_query在供应商调用前检查代理存在、启用、支持API及关联ID一致。云写入仅有tracking_number，没有可靠本地主键映射，所以本地同号多票全部阻断；不以代理或客户推测云端归属。sync_to_supabase基本信息同步、sync_tracking_to_supabase、simple_sync_tracking也独立检查身份和代理，避免绕过查询层直接写同号或停用代理记录。批量循环仍按Shipment对象处理，使用计数聚合，不建立单号键结果字典。

单票/批量：/shipments/<id>/refresh、/admin/refresh-tracking、/admin/sync-tracking-details正常唯一运单保持供应商请求及既有云payload。/admin/sync-to-supabase跳过本地同号或停用代理票。新增运单后的自动轨迹抓取同样显式传对象。

## 必须阻断的历史链

complete_sync_tracking原实现使用不存在的Shipment.tracks/Track，而且输入time/description与预期track_time/track_description不同。未创建模型或猜测映射；helper固定返回0，不写数据。refresh-full-history、auto-sync-single、auto-sync-all-safe、auto-sync-all、auto-sync-recent在查询前返回refresh:history_mapping_unavailable，避免无意义外部请求。

这些路径不能宣称保持历史同步成功兼容，它们此前实际上无法按当前模型完成；本轮按明确授权保守阻断。

## 错误/日志

刷新查询返回固定refresh:*分类，helper在safe_errors模式下不回传供应商原文或异常正文。刷新/同步路由异常提示固定；普通诊断只保留操作分类、固定HTTP码/计数等，不输出代理URL、响应或凭据。共享helper移除URL日志；未启用safe_errors的旧查询错误文本保留，以免改变已冻结查询契约。

## 未解决边界

云端是否有其他来源同号，本地无法证明；没有请求云端验证。并发新增同号与云写入之间仍可能有竞态，彻底约束须云端身份协议，不执行迁移。unique仅表示当前本地唯一，不是供应商协议真实性证明。现有截断描述、缺时间默认值、409成功等云写入规则未擅改；它们仍需后续独立批准。

手工轨迹录入时的旧云PATCH、公共查询及其他独立脚本不属于本次刷新入口修复。公共first、显式代理覆盖、客户级授权仍待处理；不宣称全项目first消除。

## 验证与回滚

使用既有临时隔离数据库和mock供应商/云端。新增8项覆盖同号多票阻断、选定NextSLS参数、停用代理全部入口零请求、失败不写与脱敏、批量主键不丢失、历史链预请求阻断、正常唯一票及基本信息同步同号阻断。

复现：/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_*.py'

原工作区备份/tmp/4a-before.patch，views原件/tmp/4a-views-before.py。仅暂存本轮差异，回滚git revert本轮提交，不reset原有工作区。没有访问真实DB/API/Supabase、部署或推送。

最终：Python3.11.18，原有289+新增8=297通过，0失败/错误/跳过；未修改旧测试断言。完整日志/tmp/4a-final.log。git diff --check通过，旧SQLAlchemy弃用提示保留。
