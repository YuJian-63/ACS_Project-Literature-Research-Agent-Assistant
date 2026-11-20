from sqlalchemy import func, select
LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 20
MONITOR_SECONDS = 10

def database_time(session):
    return session.scalar(select(func.clock_timestamp()))
