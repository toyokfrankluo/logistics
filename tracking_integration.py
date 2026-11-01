"""Only a single fictional RTB56 shadow. No HTTP client or production provider."""
import json
from flask import current_app, request
from tracking.service_types import Source, ShipmentSnapshot, QueryRequest, Response
from tracking.service import resolve_query, query_tracking


def simulated_track():
    mode = current_app.config.get('TRACKING_MODE', 'legacy')
    if mode == 'legacy' or mode not in {'shadow', 'service'}:
        return None
    # A config key is not authorization. Only a disposable isolated runtime qualifies.
    if mode == 'service' or current_app.config.get('ISOLATED_MODE') is not True:
        return ({}, '当前环境禁止所选追踪模式')
    from flask_login import current_user
    if not current_user.is_admin:
        return ({}, '模拟对比仅供管理员使用')
    numbers = request.form.get('numbers', '').strip().splitlines()
    if len(numbers) != 1 or not numbers[0].strip():
        return ({}, '模拟对比仅支持单票查询')
    from models import Shipment, db
    no = numbers[0].strip()
    with db.session.no_autoflush:
        rows = Shipment.query.filter_by(tracking_number=no).all()
        if len(rows) != 1:
            return ({}, '运单不存在或身份不唯一')
        s = rows[0]
        if ((request.form.get('customer_id') and str(s.customer_id) != request.form['customer_id'])
                or (request.form.get('agent_id') and str(s.agent_id) != request.form['agent_id'])):
            return ({}, '筛选条件与运单不一致')
        agent = s.agent
        # Only the seeded fictional identity is eligible; real credentials/URL never used.
        if (s.tracking_number != 'DEMO-001' or not agent or not agent.is_active
                or not agent.supports_api):
            return ({}, '仅允许已启用代理的虚构 DEMO-001 运单')
        manual = [f"{e.happen_time.strftime('%Y-%m-%d %H:%M')} {e.location or ''} {e.description}" for e in s.manual_tracks]
        snapshot = ShipmentSnapshot(s.id, no, agent=Source('simulation:rtb56', 'rtb56', 'customer', True))
    class Repository:
        def by_id(self, key): return snapshot if key == snapshot.local_id else None
    class FictionalProvider:
        calls = 0
        def fetch(self, attempt):
            self.calls += 1
            if self.calls != 1: raise RuntimeError('duplicate fetch')
            return Response(200, '{"success":"1","data":[{"details":[{"track_occur_date":"2026-01-02 10:00:00","track_location":"虚构地点","track_description":"虚构模拟轨迹"}]}]}')
    provider = FictionalProvider()
    plan = resolve_query(QueryRequest('backend', local_id=snapshot.local_id), Repository())
    # Exactly one acquisition, then the same immutable response for both parsers.
    captured = provider.fetch(plan.attempts[0])
    from comparison.runner import run_legacy
    old = run_legacy('backend', 'rtb56', captured.http_status, captured.body)
    lines = manual + [f"{e['time'] or ''} {e['location'] or ''} {e['description'] or ''}" for e in old['events']]
    payload = {no: {'tracks': '\n'.join(lines) or '暂无轨迹', 'error': old['error']}}
    class Replay:
        def fetch(self, attempt): return captured
    try:
        outcome = query_tracking(plan, Replay())
        from tracking.presentation import present_legacy
        new = present_legacy(outcome, 'backend')
        expected = '\n'.join(lines[len(manual):])
        category = 'equal' if new.compatible and new.payload['tracks'] == expected else 'difference'
    except Exception:
        category = 'comparison_error'
    # Fixed vocabulary only: no identity, response, event, exception or credential logs.
    current_app.logger.info('tracking_shadow:%s', category)
    return payload, '虚构 RTB56 单票模拟对比完成'
