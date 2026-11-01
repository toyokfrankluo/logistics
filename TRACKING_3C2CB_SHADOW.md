# 3C-2C-B 安全修复与模拟 shadow

范围：完整查询计划校验、严格布尔、身份一致性、状态呈现校验；仅隔离环境管理员后台/track单票DEMO-001固定虚构RTB56影子对比。无真实HTTP提供者、Supabase、同步、数据库迁移或生产配置变化。

query_tracking使用运单快照重建规范计划，对比整个attempt元组（来源、单号、顺序、阻断原因）。后台最多一次获取，公共仅规范第三方→代理链。来自调用方的快照和仓储仍是可信边界，不能把请求正文直接转换为已验证Source。严格bool不等于协议已验证；生产协议仍待确认。

外部empty+手工历史整体success仅代表有本地历史，SourceOutcome及selected仍empty。旧217项中的两项empty断言按本轮明确批准规则调整，其余未放宽。错误、blocked仍保留手工历史；没有批准旧错误文字映射，继续incompatibility。

TRACKING_MODE只从应用config读取，默认legacy，未知值legacy。shadow要求ISOLATED_MODE严格True、已登录管理员、单票DEMO-001、唯一匹配、客户/代理筛选一致、关联代理启用并支持API。供应商固定为虚构RTB56，不根据URL猜测、不读取代理凭据。不能用于其他单号。service本轮无论环境均拒绝，不自动回退联网。普通legacy代码保持原行为，既有全局first风险不在生产路径上被夹带修改。

固定响应获取一次后，comparison.runner通过AST执行真实旧fetch_tracking_from_api解析函数（HTTP为内存替身）；新服务通过Replay读取同一Response。页面显示旧解析文本及原手工历史。新服务异常只记录comparison_error，不再获取响应。日志仅equal/difference/comparison_error，不记录单号、事件、正文、凭据。comparison工具仅在这个模拟分支导入；不是生产解析层。

## 本地验收（仅临时虚构库）

在Python3.11依赖环境中执行：

```python
import dev_local
from models import db, CarrierAgent

dev_local.seed()  # dev_local强制创建独立临时库并禁用网络
with dev_local.app.app_context():
    agent = CarrierAgent.query.one()
    agent.supports_api = True
    db.session.commit()
dev_local.app.config['TRACKING_MODE'] = 'shadow'
dev_local.app.run(host='127.0.0.1', port=5056, debug=False, use_reloader=False)
```

登录local-admin/local-test-only，打开/track，输入DEMO-001，可见虚构模拟轨迹。提交两个单号、错误筛选或停用代理应拒绝模拟。关闭：将TRACKING_MODE设为legacy，或停止进程使用原dev_local启动。不会更改任何生产配置。

自动化：/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_*.py'

回滚：revert本轮提交。已有未提交工作保留，不能reset --hard。起点差异保存于/tmp/logistics-3c2cb-before.patch。views.py仅暂存本轮/track新增接入块，旧未提交改动不纳入提交。

待Astra复核：可信快照/授权范围、真实协议验证记录、错误文字映射、empty整体语义、将模拟AST比较器替换为正式响应解析边界的方案。真实service、真实shadow、公共入口、TXFBA/NextSLS/17Track/generic与同步均未获本轮启用。

最终验证：Python3.11.18，全量242通过，0失败/错误/跳过。原有217项（两项按批准empty语义更新）+新增25项。测试日志/tmp/cb-final.log；保留SQLAlchemy旧API弃用提示。本次未启动手工验收服务器，仅通过真实Flask测试客户端验证模拟入口。
