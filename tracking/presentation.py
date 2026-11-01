"""Conservative legacy rendering: impossible conversions are explicit outcomes."""
from .service_types import LegacyPresentation, Status


def present_legacy(outcome, contract):
    if contract not in {'public_json', 'public_html', 'backend'}:
        return LegacyPresentation(False, incompatibilities=('unsupported_contract_or_raw_envelope',))
    if outcome.status == Status.UNVERIFIED:
        return LegacyPresentation(False, incompatibilities=('unverified_has_no_legacy_success_representation',))
    events = outcome.selected.events if outcome.selected else ()
    if outcome.selected and outcome.selected.provider not in {'rtb56', 'txfba'}:
        return LegacyPresentation(False, incompatibilities=('provider_text_contract_unconfirmed',))
    if outcome.status == Status.EMPTY:
        # Old supplier cnmessage can determine public empty text; adapter discards it.
        if contract != 'backend':
            return LegacyPresentation(False, incompatibilities=('supplier_empty_message_unavailable',))
    failed = outcome.status in {Status.ERROR, Status.BLOCKED}
    if failed:
        return LegacyPresentation(False, incompatibilities=('legacy_error_message_requires_approved_mapping',))
    error = None
    if contract != 'backend' and outcome.manual:
        return LegacyPresentation(False, incompatibilities=('public_manual_history_policy_unresolved',))
    def raw_time(event):
        return '' if event.time.raw is None else str(event.time.raw)
    if contract == 'backend':
        lines = []
        for m in outcome.manual:
            e = m.event
            # Legacy minute formatting cannot be recovered from arbitrary time text.
            if e.time.local_time is None:
                return LegacyPresentation(False, incompatibilities=('manual_minute_time_unavailable',))
            lines.append(f"{e.time.local_time.strftime('%Y-%m-%d %H:%M')} {e.location} {e.description}")
        lines.extend(f'{raw_time(e)} {e.location} {e.description}' for e in events)
        payload = {'tracks': '\n'.join(lines) if lines else '暂无轨迹', 'error': error}
    else:
        text = '\n\n'.join((' — '.join(x for x in (e.location.strip(), e.description.strip()) if x)
                             + '\n' + raw_time(e).strip()).strip() for e in events)
        payload = {'tracks': [] if failed and contract == 'public_json' else None if failed else text,
                   'error': error}
        if contract == 'public_json':
            payload = {'order_id': outcome.customer_number, **payload}
    return LegacyPresentation(True, payload)
