# 3C-2C-F 模拟Shadow异常与隔离保护

范围：tracking_integration.py、isolated_runtime.py、dev_local.py的可信种子登记、原shadow测试夹具及新增故障测试。未修改路由、模板、TrackingService、模型、公共查询、权限或CSRF。dev_local是现有隔离开发入口，本次只增加种子登记两行，不改变业务查询。

## 异常边界

simulated_track外层覆盖环境检查、运单读取、虚构响应获取、旧解析器加载/执行和事件遍历。旧解析必须返回明确的no_explicit_error、无exception/error、有效事件列表；畸形或失败结果不伪装成功，返回固定“模拟查询失败，未生成有效旧结果”。不回传异常、路径、响应或凭据。

有效旧payload构造完成后，新服务和比较使用独立try；失败只产生auto_text_comparison_error，并返回已经计算好的旧结果。日志失败也不破坏旧结果。没有重试或再次调用旧函数的恢复路径。FictionalProvider每个请求最多fetch一次；Replay只读同一份不可变Response。

## 真实比较范围

日志前缀tracking_shadow_auto_text，分类auto_text_equal、auto_text_difference、auto_text_comparison_error；旧结果不可用时为legacy_unavailable。equal仅说明这份固定虚构响应的自动轨迹文本一致，不代表状态、手工历史、完整页面或真实协议兼容。不记录任何单号、客户、事件、原始响应、异常正文。

## 隔离与数据证明

configure(app)创建临时库时在模块私有WeakKeyDictionary登记app、目标URI、TemporaryDirectory及fixture清单。shadow在任何运单数据库查询前核对：初始化登记存在、ISOLATED_MODE严格True、临时目录存在、配置URI未改变、SQLAlchemy实际引擎URL一致、Requests及socket的全部已安装禁网守卫仍指向deny_network。

这不是普通config/环境变量令牌。请求/表单无登记接口。普通环境变量单独无法制作登记；现有隔离入口通过LOGISTICS_ISOLATED启动后真正执行configure，会创建全新临时库和安装守卫。

dev_local.seed在虚构运单提交后通过register_shadow_fixture登记主键、客户单号、代理单号、客户与代理身份。测试在可信setUp中同样登记。查询时再次核对登记；仅命名DEMO-001或伪造ISOLATED_MODE不够。登记函数仅供可信Python种子代码使用，不提供HTTP端点。应用代码执行权限、任意进程内篡改或恶意重建同身份fixture不属于此证明能防御的边界。

默认legacy不执行隔离检查或数据库读取。service仍始终拒绝；shadow仍仅管理员/单票/固定虚构RTB56/启用代理。其余未启用。

## 本地验收

先在Python3.11依赖环境进入项目目录，运行以下Python片段（使用dev_local全新临时库，禁止改为生产app启动）：

```python
import dev_local
from models import db, CarrierAgent

dev_local.seed()  # 已自动登记可信虚构数据
with dev_local.app.app_context():
    CarrierAgent.query.one().supports_api = True
    db.session.commit()
dev_local.app.config['TRACKING_MODE'] = 'shadow'
dev_local.app.run(host='127.0.0.1', port=5056, debug=False, use_reloader=False)
```

登录local-admin/local-test-only，/track单票DEMO-001应显示虚构模拟轨迹。普通用户、重复身份、筛选冲突继续拒绝。关闭：TRACKING_MODE设legacy或停止模拟进程重新按原dev_local启动。

回滚：revert本轮提交。只暂存本轮runtime和dev_local新增片段，原有未提交工作不纳入提交；起点补丁/tmp/shadow-f-before.patch。不reset工作区，不回滚数据库。

集中复核建议：检查可信运行时记录生命周期、fixture来源绑定、所有异常边界和自动文本比较范围。真实协议仍未验证，不能据此启用真实service/shadow。

最终验证：Python3.11.18，原有275+新增14=289项全部通过，0失败、0错误、0跳过；原shadow13项继续通过，未放宽断言，仅在可信测试种子中增加fixture登记。完整日志/tmp/f-full.log，git diff --check通过。手工服务器未启动，路由通过隔离Flask测试客户端验收。
