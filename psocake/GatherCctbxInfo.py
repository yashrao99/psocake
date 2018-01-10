import os
import cPickle as pickle


class Cctbx(object):

    def __init__(self, mask = None, integratedPickles = None, indexedPickles = None,
    cbfImages = None, expDir = None):

        self.mask = mask
        self.integratedPickles = []
        self.indexedPickles = []
        self.cbfImages = []

    def SetExpDir(self, instrument, expName, **kwargs):

        lowerInst = instrument.lower()
        lowerExpName = expName.lower()

        extraPath = kwargs.get('extraPath', '')

        self.expDir = '/reg/d/psdm/' + lowerInst + '/' + lowerExpName + '/' + extraPath

    def FindMask(self, maskName):

        self.maskName = maskName
        expDir = self.expDir

        for file in os.listdir(expDir):
            if maskName in file and file.endswith(".pickle"):
                self.mask = file

    def SearchIndexImageIntegrate(self, topDown=True):

        expDir = self.expDir

        for dirPath, subDirs, files in os.walk(expDir):
            for file in files:
                if file.endswith(".pickle") and "indexed" in file:
                    self.indexedPickles.append(os.path.join(dirPath,file))

                elif file.endswith(".pickle") and "integrated" in file:
                    self.integratedPickles.append(os.path.join(dirPath,file))

                elif file.endswith(".cbf"):
                    self.cbfImages.append(os.path.join(dirPath,file))

    def FindIndexedSpots(self):

        indexedPickles = self.indexedPickles


        #For more specific run # and event #. Can be replaced with current set-up
        peakFileName = '/reg/d/psdm/cxi/cxitut13/scratch/YR99/dials/r00#/0010/out/idx-'str(i+1).zfill(4)'_indexed.pickle'

        for path in indexedPickles:
            i = 5
            p = pickle.load(open(path, 'rb'))
            print '%12s %12s'%('cctbx','psana')
            print '%5s %4s %4s %4s %4s %4s %10s'%('Panel','Fast','Slow','Seg','Row','Col','Iobs')

            for i in range(p.nrows()):
                # cctbx format: panel (64), fast (194), slow (185)
                panelId = p['panel'][i]
                Iobs = p['intensity.sum.value'][i]
                fast, slow, _ = p['xyzobs.px.value'][i]
                #convert to sector (32), row (185), and column (388)
                row = slow
                col = fast + (194 * (panelId % 2))
                sector = (panelId - (panelId % 2)) // 2
                print '%5d %4d %4d %4d %4d %4d %10.2f'%(panelId, fast, slow, sector, row, col,
                Iobs)

