import GatherCctbxInfo
from GatherCctbxInfo import Cctbx
from GatherCrystFelInfo import Crystfel



class GenerateObject(object):

    def __init__(self, cctbx = None, crystfel = None, psana = None, expDir = None):

        self.cctbx = Cctbx()
        self.crystfel = Crystfel()
