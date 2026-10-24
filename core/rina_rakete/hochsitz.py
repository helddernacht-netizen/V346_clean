class HochsitzAnchor:
    def __init__(self): self.anchors={}; self.portfolio_high=0
    def get_anchor_for_symbol(self,s,p,o,ph=None): return {'symbol':s,'price':p,'type':'fallback'}
