import abc

class shockApiBase(abc.ABC):
    BaseStrength:float = 0
    ApiName:str
    @abc.abstractmethod
    def __init__(self, ModulePath:str):
        pass
    @abc.abstractmethod
    def setBaseStrength(self, strength:float):
        """向下取整"""
        pass
    @abc.abstractmethod
    def addBaseStrength(self, strength:float):
        """向下取整"""
        pass
    @abc.abstractmethod
    async def onDamaged(self, hp:int,maxHp:int):
        pass
    @abc.abstractmethod
    async def onRestart(self):
        pass
    @abc.abstractmethod
    async def onDied(self):
        pass