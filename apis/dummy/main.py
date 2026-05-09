from .. import api

class DummyApi(api.shockApiBase):
    """test api"""
    ApiName = "dummy"
    def __init__(self, ModulePath:str):
        print("using dummy(test api)")
    def setBaseStrength(self, strength:float):
        """向下取整"""
        pass
    def addBaseStrength(self, strength:float):
        """向下取整"""
        pass
    async def onDamaged(self, hp:int,maxHp:int):
        pass
    async def onRestart(self):
        pass
    async def onDied(self):
        pass