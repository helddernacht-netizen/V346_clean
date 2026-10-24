class TurtleScanner:
    def __init__(self,u): self.universe=u
    def scan(self): return [{'symbol':s,'price':0,'change':0,'score':5} for s in self.universe[:20]]
