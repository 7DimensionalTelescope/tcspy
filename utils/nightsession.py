
#%%
from tcspy.devices.observer import mainObserver
from tcspy.configuration import mainConfig
from astropy.time import Time
#%%
class NightSession(mainConfig):
    
    def __init__(self,
                 utctime : Time = None):
        super().__init__()
        if utctime is None:
            utctime = Time.now()
        self.utctime = utctime
        self.observer = mainObserver()
        self.obsnight_utc = self.set_obsnight(utctime)
        self.obsnight_ltc = self.convert_obsnight_ltc()

    def set_obsnight(self,
                     utctime : Time = None):
        if utctime is None:
            utctime = Time.now()
        class obsnight: 
            def __repr__(self):
                attrs = {name: value.iso if isinstance(value, Time) else value
                         for name, value in self.__dict__.items()}
                max_key_len = max(len(key) for key in attrs.keys())
                attrs_str = '\n'.join([f'{key:{max_key_len}}: {value}' for key, value in attrs.items()])
                return f'{self.__class__.__name__} Attributes:\n{attrs_str}'
        horizon_flat = self.config['NIGHTSESSION_SUNALT_AUTOFLAT']
        horizon_startup = self.config['NIGHTSESSION_SUNALT_STARTUP']
        horizon_observation = self.config['NIGHTSESSION_SUNALT_OBSERVATION']
        horizon_shutdown = self.config['NIGHTSESSION_SUNALT_SHUTDOWN']
        obsnight = obsnight()
                    
        # Celestial information
        obsnight.sunrise_shutdown = self.observer.tonight(utctime, horizon = horizon_shutdown)[1]
        obsnight.sunrise_civil = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon = 0)
        obsnight.sunset_civil = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= 0)        
        obsnight.sunrise_nautical = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon= -6)
        obsnight.sunset_nautical = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= -6)
        obsnight.sunrise_astro = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon= -12)
        obsnight.sunset_astro = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= -12)
        obsnight.sunrise_night = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon= -18)
        obsnight.sunset_night = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= -18)        
        # Observation information
        obsnight.sunrise_flat = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon= horizon_flat)
        obsnight.sunset_flat = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= horizon_flat)        
        obsnight.sunrise_startup = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon= horizon_startup)
        obsnight.sunset_startup = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= horizon_startup)
        obsnight.sunrise_observation = self.observer.sun_risetime(obsnight.sunrise_shutdown, mode = 'previous', horizon= horizon_observation)
        obsnight.sunset_observation = self.observer.sun_settime(obsnight.sunrise_shutdown, mode = 'previous', horizon= horizon_observation)       
        obsnight.midnight = Time((obsnight.sunset_astro.jd + obsnight.sunrise_astro.jd)/2, format = 'jd')
        obsnight.observable_hour = (obsnight.sunrise_observation - obsnight.sunset_observation).jd * 24
        obsnight.time_inputted = utctime
        obsnight.current = Time.now()
        return obsnight

    def convert_obsnight_ltc(self):
        class obsnight_ltc:
            def __repr__(self):
                attrs = {name: value.iso if isinstance(value, Time) else value
                            for name, value in self.__dict__.items()}
                max_key_len = max(len(key) for key in attrs.keys())
                attrs_str = '\n'.join([f'{key:{max_key_len}}: {value}' for key, value in attrs.items()])
                return f'{self.__class__.__name__} Attributes:\n{attrs_str}'
        obsnight_ltc = obsnight_ltc()
        obsnight_utc = self.obsnight_utc
        
        for key, value in obsnight_utc.__dict__.items():
            if isinstance(value, Time):
                local_time = self.observer.localtime(value.datetime)
                setattr(obsnight_ltc, key, Time(local_time.replace(tzinfo=None), format='datetime'))
            else:
                setattr(obsnight_ltc, key, value)
        return obsnight_ltc 
# %%
