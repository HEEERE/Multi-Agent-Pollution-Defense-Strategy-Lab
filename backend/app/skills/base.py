from abc import ABC, abstractmethod


class BaseSkill(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def run(self, payload: str) -> str:
        raise NotImplementedError
