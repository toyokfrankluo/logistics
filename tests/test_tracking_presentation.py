import unittest
from tracking.presentation import present_legacy
from tracking.service_types import *
from tracking.adapters import parse_response
from test_tracking_service import response


class PresentationTests(unittest.TestCase):
    def outcome(self, value=None):
        r = value or response()
        parsed = parse_response('rtb56', 'agent:fake', r.http_status, r.body)
        return QueryOutcome(Status(parsed.status.value), 'FAKE-CUSTOMER', selected=parsed)
    def test_public_json_exact(self):
        p = present_legacy(self.outcome(), 'public_json')
        self.assertTrue(p.compatible)
        self.assertEqual(p.payload, {'order_id': 'FAKE-CUSTOMER', 'error': None, 'tracks': '虚构地点 — 虚构事件\n2026-01-02 10:00:00'})
    def test_html_result_fields(self):
        p = present_legacy(self.outcome(), 'public_html')
        self.assertEqual(p.payload, {'error': None, 'tracks': '虚构地点 — 虚构事件\n2026-01-02 10:00:00'})
    def test_backend_text(self):
        self.assertEqual(present_legacy(self.outcome(), 'backend').payload, {'tracks': '2026-01-02 10:00:00 虚构地点 虚构事件', 'error': None})
    def test_order_duplicates_long_text(self):
        events = [{'track_description': x} for x in ('B'*2000, 'A', 'A')]
        p = present_legacy(self.outcome(response(events)), 'public_json')
        self.assertEqual(p.payload['tracks'], 'B'*2000+'\n\nA\n\nA')
    def test_unknown_time_not_invented(self):
        self.assertEqual(present_legacy(self.outcome(response([{'track_description':'虚构'}])), 'public_json').payload['tracks'], '虚构')
    def test_public_empty_incompatible(self): self.assertFalse(present_legacy(self.outcome(response([])), 'public_json').compatible)
    def test_backend_empty(self): self.assertEqual(present_legacy(self.outcome(response([])), 'backend').payload['tracks'], '暂无轨迹')
    def test_unverified_incompatible(self): self.assertFalse(present_legacy(QueryOutcome(Status.UNVERIFIED, 'FAKE'), 'public_json').compatible)
    def test_raw_envelope_incompatible(self): self.assertFalse(present_legacy(self.outcome(), 'raw_api').compatible)
    def test_failure_message_mapping_not_fabricated(self):
        p = present_legacy(QueryOutcome(Status.ERROR, 'FAKE', error='timeout'), 'public_json')
        self.assertFalse(p.compatible)
        self.assertIsNone(p.payload)
    def test_nextsls_text_not_fabricated(self):
        from tracking.types import QueryResult, QueryStatus
        o = QueryOutcome(Status.SUCCESS, 'FAKE', selected=QueryResult('nextsls', 'fake', QueryStatus.SUCCESS))
        self.assertFalse(present_legacy(o, 'public_json').compatible)
    def test_manual_backend_minute_format(self):
        from tracking.types import TrackingEvent
        from tracking.time import parse_time
        e = TrackingEvent('manual', 'manual:fake', parse_time('2026-01-01 10:12:34'), '虚构地点', '虚构手工')
        o = QueryOutcome(Status.SUCCESS, 'FAKE', manual=(ManualEvent(1, e),))
        self.assertEqual(present_legacy(o, 'backend').payload['tracks'], '2026-01-01 10:12 虚构地点 虚构手工')
        self.assertFalse(present_legacy(o, 'public_json').compatible)
