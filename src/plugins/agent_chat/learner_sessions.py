"""One durable worker per group/family; uncertainty never triggers session churn."""
from .dsh import MissingSession


async def acquire(learner, key, family, policy):
    if family == 'memory':
        manager = learner.service.memory_manager
        sid, previous = manager.state(key)
        bind = manager.bind
    elif family == 'slang':
        _, _, sid, previous = learner.store.learning_state(key)
        bind = learner.store.bind_learner
    else:
        raise ValueError('invalid_learning_family')
    if sid:
        try:
            # Reads the real preset, queue, completed turn and bridge ownership.
            # Offline, running or foreign input retains this binding and backs off.
            await learner.client.recovery_checkpoint(sid)
        except MissingSession:
            sid = None  # Only an explicit not-found allows replacement after failure.
        if sid and previous == policy:
            return sid
        if sid:
            # A deliberate policy change needs a new worker. Hide the retired one
            # through DSH's native reversible archive; preserve its durable log.
            await learner.client.archive_session(sid)
    sid = await learner.client.create_session()
    bind(key, sid, policy)
    return sid
