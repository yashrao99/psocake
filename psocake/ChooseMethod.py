import GatherCctbxInfo


class Process(object):

    def __init__(self):

        self.methodChoice = raw_input("Which software would you like to process your data with? Your options are Cctbx or CrystFEL   ")

        self.finalChoice = self.methodChoice.lower()

    @staticmethod
    def factory(self):

        if self.finalChoice == "cctbx":
            return Cctbx()

        if self.finalChoice == 'crystfel':
            return CrystFEL()

        else:
            print("You have selected an invalid argument")
