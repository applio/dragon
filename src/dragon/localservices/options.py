"""
Options objects for local services object creation messages.


All should have dict-like init/serialization.

TODO: lock type parameter in here?  Better handshake interface-wise
maybe between this and cython desirable.
"""


class ChannelOptions:
    def __init__(self, sattr='', capacity=None, block_size=None):
        self.capacity = capacity
        self.sattr = sattr
        self.block_size = block_size

    # wonder what __dict__(self) does.
    def get_sdict(self):
        return {'sattr': self.sattr,
                'capacity': self.capacity,
                'block_size': self.block_size}

    # this method seems kinda derpy in hindsight.
    @staticmethod
    def from_sdict(sdict):
        return ChannelOptions(**sdict)


class ProcessOptions:
    """Options for process creation at local services level.

    Attributes
     (e.g.)
     mon_std - whether to monitor stdout/stderr, write to stdin
               bool default True
    """
    def __init__(self, mon_std=True):
        self.mon_std = bool(mon_std)

    def get_sdict(self):
        return {'mon_std': self.mon_std}

    @staticmethod
    def from_sdict(sdict):
        return ProcessOptions(**sdict)
