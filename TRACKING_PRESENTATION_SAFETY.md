# 3C-2C-E 查询结果呈现校验

仅修改tracking/presentation.py、tests/test_tracking_presentation.py及本说明。未修改查询服务、类型、路由、模板、权限、CSRF、shadow或供应商协议。

## 校验边界

present_legacy在构造任何旧payload前执行_validate_outcome。只接受明确的QueryOutcome/Status和预期不可变集合，检查手工记录、来源唯一性、结果结构、事件归属与unknown物流状态。不修改输入、不重排/去重事件、不补时间、不丢弃错误或历史。

selected必须在sources中恰好匹配一个source_id，并与该来源的完整QueryResult相等，包括事件序列、provider、错误及待确认项。来源状态必须与QueryResult一致，来源错误必须与适配器错误一致。成功结果不能携带error；success须有事件、empty不能有事件；错误结果不能混入事件。

整体success/empty按selected事件和独立manual历史确定。selected empty+manual时整体success只表示有本地历史，外部结果仍empty。纯本地模式必须有唯一NOT_REQUESTED来源、无selected，整体状态与历史数量一致。

现有批准的回退可呈现：最多一个前置ERROR来源，然后选定的success/empty来源；此前失败诊断完整保留于原Outcome，不显示为本次选定来源失败。此层只检查结果一致性，不认证来源或批准供应商，来源计划仍由服务/可信外围负责。并行多个成功、选定来源后还有结果、混入unverified等未定组合保守阻断。

error、blocked、unverified、顶层not_requested及非法状态均不生成成功payload。失败和不兼容一律compatible=False、payload=None，调用方仍必须检查compatible。原始供应商信封、公共手工历史、特殊供应商文本、公共empty提示及未批准错误文字继续阻断。

校验是结构和语义一致性检查，不是供应商真实性认证，也不能检测一组内部自洽但整体伪造的历史。新旧业务入口尚未接入真实service，本轮不改变页面。

## 测试

原有正常兼容测试的虚构Outcome补上来源记录；本地历史样例补上NOT_REQUESTED标记。输出断言未放宽。新增20项测试覆盖selected缺失/错配、矛盾状态/错误、候选提升、部分失败回退、并行成功阻断、本地模式、unknown状态、TXFBA格式和畸形结构。原有顺序、重复、长描述、未知时间测试保留。

复现：/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_tracking_presentation.py'
全量：/tmp/logistics-dependency-check/bin/python -B -m unittest discover -s tests -p 'test_*.py'

回滚只revert本轮提交，勿reset已有工作区。起点已有差异备份/tmp/logistics-presentation-before.patch。本轮没有数据库变更、网络请求、推送或部署。

最终验证：Python3.11.18，原有255+新增20=275项全部通过，0失败、0错误、0跳过。呈现层32项通过。最终全量日志/tmp/presentation-final.log。git diff --check通过；除系统自行更新的.DS_Store外，其他原有未提交源码差异与本轮开始前逐字节一致。原有SQLAlchemy弃用提示未处理。
