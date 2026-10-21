from datetime import datetime, timedelta, timezone
from queue import Empty
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler
import pytest

from novadeck.core.models import Profile, Trigger
from novadeck.core.scheduler import ProfileScheduler, ScheduledRun, classify_run, cron_trigger

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)  # Monday


def make_scheduler(profiles=None):
    service = ProfileScheduler(timezone_=UTC, clock=lambda: NOW)
    service.replace_profiles(profiles or [])
    return service


def emit(service, scheduled_at):
    job = service.backend.get_jobs()[0]
    service._executed(JobExecutionEvent(EVENT_JOB_EXECUTED, job.id, 'default', scheduled_at))


def test_weekday_trigger_and_next_run():
    profile = Profile(name='A', triggers=[Trigger(type='schedule', time='13:30', weekdays=[0, 2, 4])])
    service = make_scheduler([profile])
    assert service.next_run(profile.id) == NOW.replace(hour=13, minute=30)
    trigger = cron_trigger(profile.triggers[0], UTC)
    tuesday = NOW + timedelta(days=1)
    assert trigger.get_next_fire_time(None, tuesday) == NOW.replace(hour=13, minute=30) + timedelta(days=2)
    assert len(service.backend.get_jobs()) == 1
    manual = Profile(name='Manual')
    service.replace_profiles([manual])
    assert service.next_run(manual.id) is None
    assert service.backend.get_jobs() == []


def test_schedules_use_local_zone_and_dst():
    zone = ZoneInfo('America/New_York')
    trigger = cron_trigger(Trigger(type='schedule', time='10:00', weekdays=[0]), zone)
    before_dst = datetime(2026, 3, 2, 9, 0, tzinfo=zone)
    first = trigger.get_next_fire_time(None, before_dst)
    second = trigger.get_next_fire_time(first, first + timedelta(seconds=1))
    assert first.hour == second.hour == 10
    assert first.utcoffset() != second.utcoffset()


@pytest.mark.parametrize('seconds,expected', [(-1, 'future'), (0, 'on_time'), (1, 'on_time'),
                                             (3, 'missed'), (599, 'missed'), (600, 'expired'), (3600, 'expired')])
def test_misfire_policy(seconds, expected):
    request = ScheduledRun('id', NOW-timedelta(seconds=seconds), 'revision')
    assert classify_run(request, NOW) == expected


def test_sleep_requests_consent_but_old_trigger_is_discarded():
    profile = Profile(name='A', triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    service = make_scheduler([profile])
    emit(service, NOW-timedelta(minutes=5))
    request = service.events.get_nowait()
    assert classify_run(request, NOW) == 'missed'
    assert service.is_current(request)
    emit(service, NOW-timedelta(minutes=10))
    assert service.events.empty()


def test_login_only_emitted_on_explicit_login_once():
    profile = Profile(name='Login', triggers=[Trigger(type='login'), Trigger(type='login')])
    service = make_scheduler([profile, Profile(name='Manual')])
    assert service.events.empty()
    service.emit_login()
    request = service.events.get_nowait()
    assert request.profile_id == profile.id and request.source == 'login'
    service.emit_login()
    assert service.events.empty()


def test_edit_delete_and_pause_invalidate_pending_requests():
    profile = Profile(name='A', triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    service = make_scheduler([profile])
    emit(service, NOW)
    request = service.events.get_nowait()
    service.pause()
    assert not service.is_current(request)
    service.resume()
    assert not service.is_current(request)
    emit(service, NOW)
    request = service.events.get_nowait()
    profile.name = 'Edited'
    service.replace_profiles([profile])
    assert not service.is_current(request)
    emit(service, NOW)
    request = service.events.get_nowait()
    service.replace_profiles([])
    assert not service.is_current(request)


def test_jobs_use_misfire_window_and_do_not_coalesce():
    profile = Profile(name='A', triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    service = make_scheduler([profile])
    job = service.backend.get_jobs()[0]
    assert job.misfire_grace_time == 600
    assert job.coalesce is False
    assert job.max_instances == 1


def test_real_apscheduler_event_reaches_queue():
    from apscheduler.triggers.date import DateTrigger
    profile = Profile(name='A', triggers=[Trigger(type='schedule', time='12:00', weekdays=[0])])
    service = ProfileScheduler(timezone_=UTC)
    try:
        service.start([profile])
        job = service.backend.get_jobs()[0]
        service.backend.reschedule_job(job.id, trigger=DateTrigger(run_date=datetime.now(UTC)+timedelta(milliseconds=60)))
        request = service.events.get(timeout=2)
        assert request.profile_id == profile.id
        assert service.is_current(request)
    finally:
        service.stop()
