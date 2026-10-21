from threading import Event, Thread
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from novadeck.core.execution import Execution, RunFinished
from novadeck.core.models import LaunchAction, Profile, SpotifyAction, SteamAction
from novadeck.core.runner import Runner, RunnerBusy
from novadeck.integrations.errors import IntegrationError


def action(identifier='10', delay=0):
    return SteamAction(app_id=identifier, display_name='Game', delay_seconds=delay)


def test_execution_order_and_partial_failures():
    seen = []
    def handler(item):
        seen.append(item.app_id)
        if item.app_id == '20':
            raise IntegrationError('steam_launch_failed')
    runner = Runner({'steam': handler})
    events = []
    results = runner.run(Profile(name='A', actions=[action('10'), action('20'), action('30')]), events.append)
    assert seen == ['10', '20', '30']
    assert [r.status for r in results] == ['succeeded', 'failed', 'succeeded']
    assert results[1].message_key == 'steam_launch_failed'
    assert [r.status for r in events] == ['running', 'succeeded', 'running', 'failed', 'running', 'succeeded']


def test_unexpected_failure_and_observer_cannot_stop_remaining_actions(caplog):
    handler = Mock(side_effect=[RuntimeError('private-argument'), None])
    events = Mock(side_effect=RuntimeError('observer-private'))
    results = Runner({'steam': handler}).run(Profile(name='A', actions=[action(), action()]), events)
    assert [r.status for r in results] == ['failed', 'succeeded']
    assert results[0].message_key == 'action_failed'
    assert 'private' not in caplog.text


def test_pending_integration_is_explicit_and_continues():
    handler = Mock()
    profile = Profile(name='A', actions=[SpotifyAction(uri='spotify:track:' + 'a'*22), action()])
    results = Runner({'steam': handler}).run(profile)
    assert results[0].message_key == 'integration_pending'
    assert results[1].status == 'succeeded'
    handler.assert_called_once()


def test_delays_are_before_each_action():
    clock = Mock()
    clock.is_set.return_value = False
    clock.wait.return_value = False
    sequence = []
    clock.wait.side_effect = lambda delay: sequence.append(('wait', delay)) or False
    runner = Runner({'steam': lambda item: sequence.append(('launch', item.app_id))})
    runner.run(Profile(name='A', actions=[action('10', 1.5), action('20', 2)]), cancel=clock)
    assert sequence == [('wait', 1.5), ('launch', '10'), ('wait', 2.0), ('launch', '20')]


def test_cancel_during_delay_skips_all_remaining():
    cancel = Event()
    waiting = Event()
    class SignalEvent:
        def is_set(self):
            return cancel.is_set()
        def wait(self, seconds):
            waiting.set()
            return cancel.wait(seconds)
    handler = Mock()
    result = []
    thread = Thread(target=lambda: result.extend(Runner({'steam': handler}).run(
        Profile(name='A', actions=[action(delay=60), action()]), cancel=SignalEvent())))
    thread.start()
    assert waiting.wait(2)
    cancel.set()
    thread.join(2)
    assert not thread.is_alive()
    handler.assert_not_called()
    assert [r.status for r in result] == ['cancelled', 'cancelled']


def test_cancel_after_current_action_does_not_undo_launched_app():
    cancel = Event()
    results = Runner({'steam': lambda item: cancel.set()}).run(
        Profile(name='A', actions=[action(), action()]), cancel=cancel)
    assert [r.status for r in results] == ['succeeded', 'cancelled']


def test_snapshot_does_not_change_with_editor_mutation():
    profile = Profile(name='A', actions=[action('10'), action('20')])
    launched = []
    def handler(item):
        launched.append(item.app_id)
        profile.actions[1].app_id = '30'
    Runner({'steam': handler}).run(profile)
    assert launched == ['10', '20']


def test_concurrent_run_rejected_and_lock_released():
    runner = Runner({})
    def handler(item):
        with pytest.raises(RunnerBusy):
            runner.run(Profile(name='B'))
    runner.handlers['steam'] = handler
    runner.run(Profile(name='A', actions=[action()]))
    assert runner.run(Profile(name='B')) == []


def test_invalid_mutated_profile_never_executes():
    profile = Profile(name='A', actions=[action()])
    profile.actions.append({'type': 'steam', 'app_id': '10; calc'})
    handler = Mock()
    with pytest.warns(UserWarning, match="Pydantic serializer"), pytest.raises(ValidationError):
        Runner({'steam': handler}).run(profile)
    handler.assert_not_called()


def test_execution_bridge_nonblocking_and_emits_completion():
    entered, release = Event(), Event()
    def handler(item):
        entered.set()
        assert release.wait(2)
    execution = Execution(Runner({'steam': handler}))
    assert execution.start(Profile(name='A', actions=[action(), action()]))
    assert entered.wait(2)
    assert execution.busy
    assert not execution.start(Profile(name='B'))
    execution.cancel()
    release.set()
    execution._thread.join(2)
    assert not execution.busy
    events = []
    while not execution.events.empty():
        events.append(execution.events.get_nowait())
    assert isinstance(events[-1], RunFinished)
    assert [r.status for r in events[-1].results] == ['succeeded', 'cancelled']
    assert execution.start(Profile(name='B'))
    execution._thread.join(2)
    assert isinstance(execution.events.get(timeout=2), RunFinished)
