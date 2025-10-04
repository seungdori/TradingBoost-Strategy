import GRID.strategy as strategy


# Pop all data from queue.
# After calling this function, the queue will be empty.
def get_trading_messages(exchange_name: str) -> list[str]:
    message_queue = strategy.get_trading_message_queue()
    messages: list[str] = []

    # Todo: impl exchange logs

    while not message_queue.empty():
        messages.append(message_queue.get())

    return messages


def put_trading_message(message: str):
    message_queue = strategy.get_trading_message_queue()
    message_queue.put(message)
