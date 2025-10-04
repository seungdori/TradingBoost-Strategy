# Trading state
from pydantic import BaseModel


class BotState(BaseModel):
    state: dict = {}


bot_state = BotState()


class BotStateStore(BaseModel):
    app: BotState = bot_state


store = BotStateStore()