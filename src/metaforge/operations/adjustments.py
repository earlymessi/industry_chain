"""Identify the confirmed execution change behind an adjustment calculation."""

def has_pending_change(state):
    if not state or not state.get('last_event') or int(state.get('event_seq') or 0)<=0:
        return False
    handled=state.get('last_adjustment') or {}
    if not handled:return True
    if handled.get('source_event_seq') is not None:
        return int(state['event_seq'])>int(handled['source_event_seq'])
    return float(state['last_event'].get('applied_at') or 0)>float(handled.get('applied_at') or 0)


def adjustment_trigger(snapshot):
    event=snapshot.get('last_event') or {}
    return {'kind':'event' if has_pending_change(snapshot) else 'baseline',
            'event_seq':int(snapshot.get('event_seq') or 0),'event_type':event.get('type'),
            'target_id':event.get('target_id'),'event_at':event.get('applied_at'),
            'constraint_version':snapshot.get('constraint_version')}
