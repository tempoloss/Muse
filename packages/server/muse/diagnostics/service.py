from muse.diagnostics.domain import PlayerLog, player_log_line
from muse.shared.clock import Clock


class PlayerLogService:
    def __init__(self, log: PlayerLog, clock: Clock) -> None:
        self.log = log
        self.clock = clock

    async def record(self, user_id: str, user_agent: str, event: str, track_id: int | None) -> None:
        line = player_log_line(self.clock.now(), user_id, user_agent, event, track_id)
        await self.log.append(line)
