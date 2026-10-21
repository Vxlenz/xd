"""APScheduler emits intents only; consent and execution belong to the UI thread."""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from queue import Queue
from threading import RLock
from typing import Literal

from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from tzlocal import get_localzone

from .models import Profile, Trigger


@dataclass(frozen=True)
class ScheduledRun:
    profile_id: str
    scheduled_at: datetime
    revision: str
    source: Literal['schedule', 'login'] = 'schedule'


def classify_run(request: ScheduledRun, now: datetime) -> Literal['on_time', 'missed', 'expired', 'future']:
    delay = (now - request.scheduled_at).total_seconds()
    if delay < 0:
        return 'future'
    if delay >= 600:
        return 'expired'
    # Ignore normal scheduler/queue jitter. Longer delays require explicit consent.
    return 'missed' if delay > 2 and request.source == 'schedule' else 'on_time'


def cron_trigger(trigger: Trigger, timezone_) -> CronTrigger:
    if trigger.type != 'schedule':
        raise ValueError('not_a_schedule')
    hour, minute = map(int, trigger.time.split(':'))
    return CronTrigger(day_of_week=','.join(map(str, trigger.weekdays)), hour=hour,
                       minute=minute, second=0, timezone=timezone_)


def _tick() -> None:
    # A no-op gives the listener the exact scheduled_run_time, including after sleep.
    return


class ProfileScheduler:
    def __init__(self, *, timezone_=None, backend=None, clock=None):
        self.timezone = timezone_ if timezone_ is not None else get_localzone()
        self.backend = backend if backend is not None else BackgroundScheduler(timezone=self.timezone)
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self.events: Queue[ScheduledRun] = Queue()
        self.paused = False
        self._lock = RLock()
        self._profiles: dict[str, Profile] = {}
        self._revisions: dict[str, str] = {}
        self._jobs: dict[str, tuple[str, str]] = {}
        self._login_emitted = False
        self._started = False
        self._epoch = 0
        self.backend.add_listener(self._executed, EVENT_JOB_EXECUTED)

    def start(self, profiles: list[Profile], *, login: bool = False) -> None:
        self.replace_profiles(profiles)
        self.backend.start()
        self._started = True
        if login:
            self.emit_login()

    def replace_profiles(self, profiles: list[Profile], *, force: bool = False) -> None:
        snapshots = [Profile.model_validate_json(profile.model_dump_json()) for profile in profiles]
        with self._lock:
            if not force and self._profiles == {profile.id: profile for profile in snapshots}:
                return
            self.backend.remove_all_jobs()
            self._profiles = {profile.id: profile for profile in snapshots}
            self._revisions = {profile.id: sha256((str(self._epoch) + profile.model_dump_json()).encode()).hexdigest() for profile in snapshots}
            self._jobs = {}
            for profile in snapshots:
                for index, trigger in enumerate(profile.triggers):
                    if trigger.type != 'schedule':
                        continue
                    # Revision in job ID prevents old worker completions matching an edited profile.
                    revision = self._revisions[profile.id]
                    job_id = f'{profile.id}:{index}:{revision}'
                    self._jobs[job_id] = (profile.id, revision)
                    self.backend.add_job(_tick, trigger=cron_trigger(trigger, self.timezone),
                                         id=job_id, coalesce=False, misfire_grace_time=600,
                                         max_instances=1, replace_existing=True)

    def _executed(self, event: JobExecutionEvent) -> None:
        with self._lock:
            entry = self._jobs.get(event.job_id)
            if not entry or self.paused:
                return
            request = ScheduledRun(entry[0], event.scheduled_run_time, entry[1])
            if classify_run(request, self.clock()) != 'expired':
                self.events.put(request)

    def emit_login(self) -> None:
        with self._lock:
            if self._login_emitted:
                return
            self._login_emitted = True
            for profile in self._profiles.values():
                if any(trigger.type == 'login' for trigger in profile.triggers):
                    self.events.put(ScheduledRun(profile.id, self.clock(), self._revisions[profile.id], 'login'))

    def is_current(self, request: ScheduledRun) -> bool:
        with self._lock:
            return not self.paused and self._revisions.get(request.profile_id) == request.revision

    def next_run(self, profile_id: str) -> datetime | None:
        with self._lock:
            if self.paused or profile_id not in self._profiles:
                return None
            now = self.clock().astimezone(self.timezone)
            times = [cron_trigger(trigger, self.timezone).get_next_fire_time(None, now)
                     for trigger in self._profiles[profile_id].triggers if trigger.type == 'schedule']
            return min((time for time in times if time is not None), default=None)

    def pause(self) -> None:
        with self._lock:
            self.paused = True
            if self._started:
                self.backend.pause()

    def resume(self) -> None:
        with self._lock:
            # Deliberately paused schedules are not misfires and must not be replayed.
            self._epoch += 1
            self.replace_profiles(list(self._profiles.values()), force=True)
            self.paused = False
            if self._started:
                self.backend.resume()

    def stop(self) -> None:
        if self._started:
            self.backend.shutdown(wait=False)
            self._started = False
