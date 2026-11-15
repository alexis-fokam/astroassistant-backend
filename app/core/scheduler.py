from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()


async def sample_periodic_task():
    print("hello")


def init_scheduler():
    scheduler.add_job(
        sample_periodic_task,
        trigger=CronTrigger(hour=0, minute=0),
        id="sample_periodic_task",
        replace_existing=True,
    )
