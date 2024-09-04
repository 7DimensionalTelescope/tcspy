
#%%
from tcspy.action.level1 import *
from tcspy.action.level2 import *

from tcspy.devices import   SingleTelescope
from multiprocessing import Event
#%%
tel = SingleTelescope(21)
abort_action = Event()
#%%
ChangeFilter(tel, abort_action).run('r')
# %%
ChangeFocus(tel, abort_action).run(31000)
# %%
Connect(tel, abort_action).run()
# %%
Disconnect(tel, abort_action).run()
# %%
Park(tel, abort_action).run()
# %%
Exposure(tel, abort_action).run(frame_number=1, exptime = 10, filter_ = 'g', imgtype = 'DARK')
# %%
FansOff(tel, abort_action).run()
# %%
FansOn(tel, abort_action).run()
# %%
SlewAltAz(tel, abort_action).run(alt = 45, az = 180)
# %%
SlewRADec(tel, abort_action).run(ra = 300, dec = -50)
# %%
TrackingOff(tel, abort_action).run()
# %%
TrackingOn(tel, abort_action).run()
# %%
Unpark(tel, abort_action).run()
# %%
Warm(tel, abort_action).run(10)
# %%

#%%

AutoFlat(tel, abort_action).run(5, 0, 1)
#%%
SingleObservation(tel, abort_action).run(exptime = 5, count = 2, specmode = 'specall', binning=  1, imgtype = 'Light', ra = 350, dec = -20, obsmode = 'Spec')
# %%
from tcspy.action import MultiAction
# %%
list_telescopes = [#SingleTelescope(1),
                        SingleTelescope(2),
                        SingleTelescope(3),
                        SingleTelescope(5),
                        SingleTelescope(6),
                        SingleTelescope(7),
                        SingleTelescope(8),
                        SingleTelescope(9),
                    #    SingleTelescope(10),
                        SingleTelescope(11),
                        ]
# %%
MultiAction(list_telescopes, dict(position = -3000, is_relative = True), ChangeFocus, Event()).run()
# %%
