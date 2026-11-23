"""Hamilton robots through PyLabRobot 1.0: the STAR family (star.py) and the Prep (prep.py), each
with PyLabRobot's own simulator. The Nimbus and the Vantage, which PyLabRobot 1.0.0b1 drives only
through pylabrobot.legacy, are in plr_ivoryos.legacy."""

from plr_ivoryos.hamilton.prep import (Prep, PrepCoreGrippers, PrepHead8, PrepHeaterShaker, PrepLights,
                                       PrepPipettes)
from plr_ivoryos.hamilton.star import (STAR, STARAutoload, STARCoreGrippers, STARHead96, STARHead384, STARiSWAP,
                                       STARPipettes)

__all__ = ["STAR", "STARPipettes", "STARHead96", "STARHead384", "STARiSWAP", "STARCoreGrippers", "STARAutoload",
           "Prep", "PrepPipettes", "PrepHead8", "PrepCoreGrippers", "PrepHeaterShaker", "PrepLights"]
