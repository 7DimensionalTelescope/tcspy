#%%
# Other modules
import os
import json
import uuid
from astroplan import FixedTarget, is_event_observable
from astroplan import AltitudeConstraint, AirmassConstraint, MoonSeparationConstraint, GalacticLatitudeConstraint, AtNightConstraint
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
import numpy as np
import datetime
import matplotlib.pyplot as plt
# TCSpy modules
from tcspy.devices.observer import mainObserver
from tcspy.configuration import mainConfig
from tcspy.utils.exception import *


class SingleTarget(mainConfig):
    """
    Represents a single observational target for a telescope.
    This class provides functionality to define and manage properties and observation parameters
    of a single target. It includes methods to calculate observability, alt-az coordinates,
    rise and set times, and other relevant information.
    
    Parameters
    ----------
    observer : mainObserver
        An instance of mainObserver representing the observer.
    ra : float, optional
        The right ascension of the target, in degrees.
    dec : float, optional
        The declination of the target, in degrees.
    alt : float, optional
        The altitude of the target, in degrees.
    az : float, optional
        The azimuth of the target, in degrees.
    name : str, optional
        The name of the target.
    objtype : str, optional
        The type of the target.
    exptime : float or str, optional
        The exposure time for the target.
    count : int or str, optional
        The number of counts for the target.
    filter_ : str, optional
        The filter used for observation.
    binning : int or str, optional
        The binning factor for observation.
    specmode : str, optional
        The spectral mode used for observation.
    obsmode : str, optional
        The observation mode.
    ntelescope : int, optional
        The number of telescopes.
        
    Attributes
    ----------
    ra : float or None
        The right ascension of the target, in degrees.
    dec : float or None
        The declination of the target, in degrees.
    alt : float or None
        The altitude of the target, in degrees.
    az : float or None
        The azimuth of the target, in degrees.
    name : str
        The name of the target.
    objtype : str or None
        The type of the target.
    exptime : float or str or None
        The exposure time for the target.
    count : int or str or None
        The number of counts for the target.
    filter_ : str or None
        The filter used for observation.
    binning : int or str or None
        The binning factor for observation.
    specmode : str or None
        The spectral mode used for observation.
    obsmode : str or None
        The observation mode.
    ntelescope : int
        The number of telescopes.
    exist_exposureinfo : bool
        Indicates whether exposure information is provided.
    ra_hour : float or None
        The right ascension of the target, in hours.
    dec_deg : float or None
        The declination of the target, in degrees.
    
    Methods
    -------
    is_observable(utctime: datetime or Time = None) -> bool
        Determines whether the target is observable at the specified time or at the current time.
    altaz(utctime: datetime or Time = None) -> SkyCoord
        Calculate the alt-az coordinates of the target for a given time(s) in UTC.
    risetime(utctime: datetime or Time = None, mode: str = 'next', horizon: float = 30) -> Time
        Calculate the next rise time of the target as seen by the observer.
    settime(utctime: datetime or Time = None, mode: str = 'nearest', horizon: float = 30) -> Time
        Calculate the time when the target sets below the horizon.
    meridiantime(utctime: datetime or Time = None, mode: str = 'nearest') -> Time
        Calculate the time at which the target passes through the observer's meridian.
    hourangle(utctime: datetime or Time = None) -> Angle
        Calculate the hour angle of the target(s) at the specified time(s).
    staralt(utctime : datetime or Time or np.array = None)
        Creates a plot of the altitude and azimuth of a celestial object.
    """
    
    def __init__(self,
                 observer : mainObserver,
                 
                 # Target information
                 ra : float = None,
                 dec : float = None,
                 alt : float = None,
                 az : float = None,
                 name : str = '',
                 objtype : str = None,
                 id_ : str = None,
                 note : str = None,
                 comment : str = None,
                 is_ToO : bool = False,
                 is_rapidToO : bool = False,
                 
                 # Exposure information
                 exptime : float or str = None,
                 count : int or str = None,
                 obsmode : str = None,
                 filter_ : str = None,
                 specmode : str = None,
                 colormode : str = None,
                 ntelescope : int = 1,
                 gain : int = 2750,
                 binning : int or str = 1,
                 ):
        
        super().__init__()
        self._observer = observer
        self._astroplan_observer = observer.status['observer']
        self._constraints = self._get_constraints(**self.config)

        self.ra = ra
        self.dec = dec
        self.alt = alt
        self.az = az
        self.name = name
        self.objtype = objtype
        self._target = None
        self._coordtype = None
        self.ra_hour = None
        self.dec_deg = None
        self._id = id_
        self.note = note
        self.comment = comment
        self.is_ToO = is_ToO
        self.is_rapidToO = is_rapidToO
        
        
        if (not isinstance(alt, type(None))) & (not isinstance(az, type(None))):
            self._coordtype = 'altaz'
            self.alt = alt
            self.az = az
            self.coordinate = self._get_coordinate_altaz(alt = alt, az = az)
            self._target = self._get_target(self.coordinate, name)
     
        if (not isinstance(ra, type(None))) & (not isinstance(dec, type(None))):
            self._coordtype = 'radec'
            self.coordinate = self._get_coordinate_radec(ra = ra, dec = dec)
            self._target = self._get_target(self.coordinate, name)
            altaz = self.altaz()
            self.ra = self.coordinate.ra.deg
            self.dec = self.coordinate.dec.deg
            self.ra_hour = self.coordinate.ra.hour
            self.dec_deg = self.coordinate.dec.deg
            self.alt = altaz.alt.value
            self.az = altaz.az.value
            
        elif (isinstance(alt, type(None))) & (isinstance(az, type(None))) & (isinstance(ra, type(None))) & (isinstance(dec, type(None))):
            pass
        
        else:
            pass
            
        self.exptime = exptime
        self.count = count
        self.filter_ = filter_
        self.binning = binning
        self.gain = gain
        self.specmode = specmode
        self.colormode = colormode
        self.obsmode = obsmode
        self.ntelescope = ntelescope
        self.exist_exposureinfo = False
        if (self.exptime is not None) & (self.count is not None) & (self.binning is not None) & (self.obsmode is not None):
            self.exist_exposureinfo = True
                    
    def __repr__(self):
        txt = f'SingleTarget(Name = {self.name}, TargetType = {self._coordtype}, ExposureInfo = {self.exist_exposureinfo})'
        return txt

    @property
    def status(self):
        """Combines exposure information and target information into a single dictionary.

        Returns
        -------
        dict
            A dictionary containing both exposure information and target information.
        """
        return{**self.exposure_info, **self.target_info}
    
    @property
    def exposure_info(self):
        """Collects and formats exposure information.

        Returns
        -------
        exposureinfo: dict
            A dictionary containing the following fields:
                - exptime: the exposure time.
                - count: the exposure count.
                - filter_: the current filter.
                - binning: the binning setting.
                - obsmode: the observation mode.
                - specmode: the spectroscopy mode.
                - specmode_filter: the filter used in spectroscopy mode.
                - ntelescope: the number of telescopes.
        """
        exposureinfo = dict()
        exposureinfo['exptime'] = self.exptime
        exposureinfo['count'] = self.count
        exposureinfo['filter_'] = self.filter_
        exposureinfo['binning'] = self.binning
        exposureinfo['gain'] = self.gain
        exposureinfo['obsmode'] = self.obsmode
        exposureinfo['specmode'] = self.specmode
        exposureinfo['specmode_filter'] = None
        exposureinfo['colormode'] = self.colormode
        exposureinfo['colormode_filter'] = None
        exposureinfo['ntelescope'] = self.ntelescope
        
        # Check whether all exposure information is inputted
        if self.exist_exposureinfo:
            filter_str = exposureinfo['filter_']
            format_exposure = self._format_expinfo(filter_str = str(filter_str),
                                                   exptime_str = str(self.exptime),
                                                   count_str = str(self.count),
                                                   binning_str = str(self.binning))

            exposureinfo['exptime'] = format_exposure['exptime']
            exposureinfo['count'] = format_exposure['count']
            exposureinfo['filter_'] = format_exposure['filter_']
            exposureinfo['binning'] = format_exposure['binning']
            exposureinfo['exptime_tot'] = format_exposure['exptime_tot']
        
        obsmode_lower = self.obsmode.lower() if self.obsmode else ''
        if obsmode_lower == 'spec' and self.specmode and self.specmode.upper() != 'NONE':
            filter_info = self._get_filters_from_specmode()
            filter_str = list(filter_info.values())[0]
            format_exposure = self._format_expinfo(filter_str = str(filter_str),
                                                   exptime_str = str(self.exptime),
                                                   count_str = str(self.count),
                                                   binning_str = str(self.binning))
            exposureinfo['exptime'] = format_exposure['exptime']
            exposureinfo['count'] = format_exposure['count']
            exposureinfo['filter_'] = exposureinfo['filter_']
            exposureinfo['binning'] = format_exposure['binning']
            exposureinfo['exptime_tot'] = format_exposure['exptime_tot']
            exposureinfo['specmode_filter'] = filter_info

        if obsmode_lower in ('color', 'deep') and self.colormode and self.colormode.upper() != 'NONE':
            filter_info = self._get_filters_from_colormode()
            filter_str = list(filter_info.values())[0]
            format_exposure = self._format_expinfo(filter_str = str(filter_str),
                                                   exptime_str = str(self.exptime),
                                                   count_str = str(self.count),
                                                   binning_str = str(self.binning))
            exposureinfo['exptime'] = format_exposure['exptime']
            exposureinfo['count'] = format_exposure['count']
            exposureinfo['filter_'] = exposureinfo['filter_']
            exposureinfo['binning'] = format_exposure['binning']
            exposureinfo['exptime_tot'] = format_exposure['exptime_tot']
            exposureinfo['colormode_filter'] = filter_info
        return exposureinfo
    
    @property
    def target_info(self):
        """
        Returns a dictionary with information about the current status of the target.
        
        Returns
        -------
        targetinfo : dict
            A dictionary containing the following fields:
                - update_time: the current time in ISO format.
                - jd : the current time in JD format
                - name: the name of the target.
                - ra: the right ascension of the target.
                - dec: the declination of the target.
                - alt: the altitude of the target in degrees.
                - az: the azimuth of the target in degrees.
                - coordtype : the coordinate type defined ('radec' or 'altaz')
                - hourangle: the hour angle of the target in degrees.
                - is_observable: a boolean indicating whether the target is currently observable.
        """
        targetinfo = dict()
        targetinfo['update_time'] = Time.now().isot
        targetinfo['jd'] = "{:.6f}".format(Time.now().jd)
        targetinfo['ra'] = None
        targetinfo['dec'] = None
        targetinfo['ra_hour'] = None
        targetinfo['dec_deg'] = None
        targetinfo['ra_hour_hms'] = None
        targetinfo['dec_deg_dms'] = None
        targetinfo['alt'] = None
        targetinfo['az'] = None
        targetinfo['coordtype'] = None
        targetinfo['hourangle'] = None
        targetinfo['is_observable'] = None
        targetinfo['moonsep'] = None
        targetinfo['name'] = self.name
        targetinfo['objtype'] = self.objtype
        targetinfo['id_'] = self._id
        targetinfo['note'] = self.note
        targetinfo['comment'] = self.comment
        targetinfo['is_ToO'] = self.is_ToO
        targetinfo['is_rapidToO'] = self.is_rapidToO
        
        if self._coordtype == 'altaz':
            targetinfo['alt'] = self.alt
            targetinfo['az'] = self.az
            targetinfo['coordtype'] = self._coordtype
            targetinfo['is_observable'] = self.is_observable(utctime = targetinfo['update_time'])
        
        elif self._coordtype == 'radec':
            targetinfo['ra'] = self.ra
            targetinfo['dec'] = self.dec
            targetinfo['ra_hour'] = self.ra_hour
            targetinfo['dec_deg'] = self.dec_deg
            targetinfo['ra_hour_hms'] = self.coordinate.ra.to_string(unit="hourangle", sep=":", precision=2, pad=True)
            targetinfo['dec_deg_dms'] = self.coordinate.dec.to_string(unit="deg", sep=":", precision=2, pad=True)
            targetinfo['alt'] = self.alt
            targetinfo['az'] = self.az
            targetinfo['coordtype'] = self._coordtype
            targetinfo['hourangle'] = self.hourangle(utctime = targetinfo['update_time']).to_string(sep = " ")
            targetinfo['is_observable'] = self.is_observable(utctime = targetinfo['update_time']) 
            targetinfo['moonsep'] = self.moon_sep(utctime = targetinfo['update_time'])
        else:
            pass
        return targetinfo
    
    def moon_sep(self,
                 utctime : datetime or Time or np.array = None):
        """
        Calculate the separation between the Moon and the target.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time at which to calculate the separation. If not provided, the current time will be used.

        Returns
        -------
        moonsep : astropy.coordinates.Angle
            The separation between the Moon and the target.
        """
        if self._coordtype == 'radec':
            
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            moon_coord = self._observer.moon_radec(utctime)
            target_coord = self.coordinate
            moonsep = np.round(moon_coord.separation(target_coord).value,2)
            return moonsep
        else:
            return None
        
    def is_observable(self,
                      utctime : datetime or Time or np.array = None) -> bool:
        """
        Determines whether the target is observable at the specified time or at the current time.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time at which to check observability. Defaults to the current time.
            
        Returns
        -------
        bool
            True if the target is observable, False otherwise.
        """
        if self._coordtype == 'radec':
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            is_observable = is_event_observable(constraints = self._constraints, observer = self._astroplan_observer, target = self._target, times = utctime)[0][0]
        
        elif self._coordtype == 'altaz':
            if (self.alt > self.config['TARGET_MINALT']) & (self.alt < self.config['TARGET_MAXALT']):
                is_observable = True
            else:
                is_observable = False
                
        return is_observable 
        
    def altaz(self,
              utctime : datetime or Time or np.array = None) -> SkyCoord:
        """
        Calculate the alt-az coordinates of the target for a given time(s) in UTC.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time(s) to calculate the alt-az coordinates for, in UTC. If not provided, the current time will be used. 

        Returns
        -------
        SkyCoord
            The alt-az coordinates of the target at the specified time(s).
        """
        if self._coordtype == 'radec':
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            return self._astroplan_observer.altaz(utctime, target = self._target)
        else:
            return None
        
    def risetime(self,
                 utctime : datetime or Time or np.array = None ,
                 mode : str = 'next',
                 horizon : float = 30) -> Time:
        """
        Calculate the next rise time of the target as seen by the observer.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time to start searching for the next rise time. If not provided, the current time will be used.
        mode : str, optional
            The method used to determine the rise time. Possible values are 'next' (the next rise time), 'previous' (the previous rise time), or 'nearest' (the nearest rise time). Default is 'next'.
        horizon : float, optional
            The altitude of the horizon, in degrees. Default is 30.

        Returns
        -------
        Time
            The rise time of the target as seen by the observer.

        """
        if self._coordtype == 'radec':
            if utctime == None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            return self._astroplan_observer.target_rise_time(utctime, target = self._target, which = mode, horizon = horizon*u.deg)
        else:
            return None
        
    def settime(self,
                utctime : datetime or Time or np.array = None,
                mode : str = 'nearest',
                horizon : float = 30) -> Time:
        """
        Calculate the time when the target sets below the horizon.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time to use as the reference time for the calculation, by default the current time.
        mode : str, optional
            Set to 'nearest', 'next' or 'previous', by default 'nearest'.
        horizon : float, optional
            The altitude of the horizon in degrees. Default is 30.

        Returns
        -------
        settime : Time
            The time when the target sets below the horizon.
        """
        if self._coordtype == 'radec':
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            return self._astroplan_observer.target_set_time(utctime, self._target, which = mode, horizon = horizon*u.deg)
        else:
            return None
    
    def meridiantime(self,
                     utctime : datetime or Time or np.array = None,
                     mode : str = 'nearest') -> Time:
        """
        Calculate the time at which the target passes through the observer's meridian.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time at which to calculate the meridian transit time. If not provided, the current time will be used.
        mode : str, optional
            Set to 'nearest', 'next' or 'previous', by default 'nearest'.
            
        Return
        -------
        meridiantime : Time
            The time at which the target passes through the observer's meridian.
        """
        if self._coordtype == 'radec':
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            return self._astroplan_observer.target_meridian_transit_time(utctime, self._target, which = mode)
        else:
            return None
        
    def hourangle(self,
                  utctime : datetime or Time or np.array = None):
        """
        Calculate the hour angle of the target for a given time(s) in UTC.

        Parameters
        ----------
        utctime : datetime or Time, optional
            The time(s) to calculate the hour angle of the target for, in UTC. If not provided, the current time will be used. 

        Returns
        -------
        hourangle : astropy.coordinates.Angle
            The hour angle of the target(s) at the specified time(s).
        """
        if self._coordtype == 'radec':
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            if not isinstance(self._target, FixedTarget):
                raise ValueError('No target is specified for hourangle')
            return self._astroplan_observer.target_hour_angle(utctime, self._target)
        else:
            return None
    
    def staralt(self,
                utctime : datetime or Time or np.array = None):
        """
        Creates a plot of the altitude and azimuth of a celestial object.
        
        Parameters
        ----------
        utctime : datetime or Time or np.array, optional
            The time(s) for which to calculate the altitude and azimuth of the celestial object. 
            If not provided, the current time is used.
        """
        if self._coordtype == 'radec':
            now = Time.now()
            if utctime is None:
                utctime = Time.now()
            if not isinstance(utctime, Time):
                utctime = Time(utctime)
            astro_sunsettime  = self._observer.sun_settime(utctime, horizon = -18)
            astro_sunrisetime = self._observer.sun_risetime(astro_sunsettime, horizon = -18, mode = 'next')
            sunsettime = self._observer.sun_settime(utctime, horizon = 0)
            sunrisetime = self._observer.sun_risetime(sunsettime, horizon = 0, mode = 'next')
            time_range_start, time_range_end = sunsettime.datetime - datetime.timedelta(hours = 2), sunrisetime.datetime + datetime.timedelta(hours = 2)
            time_axis = np.arange(time_range_start, time_range_end, datetime.timedelta(minutes = 5))
            moon_altaz = self._observer.moon_altaz(time_axis)
            sun_altaz = self._observer.sun_altaz(time_axis)
            target_altaz = self.altaz(time_axis)
            plt.figure(dpi = 300, figsize = (10, 4))
            if (now.datetime < time_range_end + datetime.timedelta(hours = 3)) & (now.datetime > time_range_start - datetime.timedelta(hours = 3)):
                plt.axvline(now.datetime, linestyle = '--', c='r', label = 'Now')
            color_target = ['k' if alt > self.config['TARGET_MINALT'] else 'b' for alt in target_altaz.alt.value]
            plt.scatter(moon_altaz.obstime.datetime, moon_altaz.alt.value, c = 'b', cmap = 'viridis', s = 10, marker = '.', label ='Moon')
            plt.scatter(sun_altaz.obstime.datetime, sun_altaz.alt.value, c = 'r', cmap = 'viridis', s = 15, marker = '.', label = 'Sun')
            plt.scatter(target_altaz.obstime.datetime, target_altaz.alt.value, c = color_target, s = 30, marker = '*', label = 'Target')
            plt.fill_betweenx([10,90], astro_sunsettime.datetime, astro_sunrisetime.datetime, alpha = 0.1)
            plt.fill_betweenx([10,90], sunsettime.datetime, sunrisetime.datetime, alpha = 0.1)
            plt.axvline(x=astro_sunrisetime.datetime, linestyle = '-', c='k', linewidth = 0.5)
            plt.axvline(x=astro_sunsettime.datetime, linestyle = '-', c='k', linewidth = 0.5)
            plt.axvline(x=sunrisetime.datetime, linestyle = '--', c='k', linewidth = 0.5)
            plt.axvline(x=sunsettime.datetime, linestyle = '--', c='k', linewidth = 0.5)
            plt.text(astro_sunsettime.datetime-datetime.timedelta(minutes=0), 92, 'Twilight', fontsize = 10)
            plt.text(sunsettime.datetime-datetime.timedelta(minutes=00), 92, 'S.set', fontsize = 10)
            plt.text(sunrisetime.datetime-datetime.timedelta(minutes=00), 92, 'S.rise', fontsize = 10)
            plt.xlim(time_range_start - datetime.timedelta(hours = 1), time_range_end + datetime.timedelta(hours = 1))
            plt.ylim(10, 90)
            plt.legend(loc = 1)
            plt.xlabel('UTC [mm-dd hh]')
            plt.ylabel('Altitude [deg]')
            plt.grid()
            plt.colorbar(label = 'Azimuth [deg]')
            plt.xticks(rotation = 45)
        else:
            return None

    def _get_filters_from_specmode(self):
        specmode_file = self.config['SPECMODE_FOLDER'] + f'{self.specmode}.specmode'
        is_exist_specmodefile = os.path.isfile(specmode_file)
        if is_exist_specmodefile: 
            with open(specmode_file, 'r') as f:
                specmode_dict = json.load(f)
            all_filters_dict = dict()
            for tel_name, filters in specmode_dict.items():
                filters_str = ','.join(filters)
                all_filters_dict[tel_name] = filters_str
            return all_filters_dict
        else:
            raise SpecmodeRegisterException(f'Specmode : {self.specmode} is not registered in {self.config["SPECMODE_FOLDER"]}')

    def _get_filters_from_colormode(self):
        colormode_file = self.config['COLORMODE_FOLDER'] + f'{self.colormode}.colormode'
        is_exist_colormodefile = os.path.isfile(colormode_file)
        if is_exist_colormodefile: 
            with open(colormode_file, 'r') as f:
                colormode_dict = json.load(f)
            all_filters_dict = dict()
            for tel_name, filters in colormode_dict.items():
                filters_str = ','.join(filters)
                all_filters_dict[tel_name] = filters_str
            return all_filters_dict
        else:
            raise ColormodeRegisterException(f'Colormode : {self.colormode} is not registered in {self.config["COLORMODE_FOLDER"]}')

    def _format_expinfo(self,
                        filter_str : str,
                        exptime_str : str,
                        count_str : str,
                        binning_str : str = '1',
                        ):
        format_expinfo = dict()
        format_expinfo['filter_'] = filter_str
        format_expinfo['exptime'] = exptime_str
        format_expinfo['count'] = count_str
        format_expinfo['binning'] = binning_str
        filter_list = format_expinfo['filter_'].split(',')
        len_filt = len(filter_list)        
        
        # Exposure information
        format_explistinfo = dict()
        for kwarg, value in format_expinfo.items():
            valuelist = value.split(',')
            if len_filt != len(valuelist):
                valuelist = [valuelist[0]] * len_filt
            formatted_value = ','.join(valuelist)
            format_expinfo[kwarg] = formatted_value
            format_explistinfo[kwarg] = valuelist
        totexp = 0
        for exptime, count in zip(format_explistinfo['exptime'], format_explistinfo['count']):
            totexp += float(exptime) * float(count)
        format_expinfo['exptime_tot'] = totexp
        return format_expinfo
    
    def _get_coordinate_radec(self,
                              ra : float,
                              dec : float,
                              frame : str = 'icrs') -> SkyCoord:
        return SkyCoord(ra = ra, dec = dec, frame = frame, unit = (u.deg, u.deg))

    def _get_coordinate_altaz(self,
                              alt : float,
                              az : float) -> SkyCoord:
        return SkyCoord(alt = alt, az = az, frame = 'altaz', unit = u.deg)
        
    def _get_target(self,
                    coord,
                    target_name : str = '') -> FixedTarget:
        return FixedTarget(coord = coord, name = target_name)
    
    def _get_constraints(self,
                         TARGET_MINALT : float = None,
                         TARGET_MAXALT : float = None,
                         TARGET_MOONSEP : float = None,
                         **kwargs) -> list:
        constraint_all = []
        if (TARGET_MINALT != None) & (TARGET_MAXALT != None):
            constraint_altitude = AltitudeConstraint(min = TARGET_MINALT * u.deg, max = TARGET_MAXALT * u.deg, boolean_constraint = True)
            constraint_all.append(constraint_altitude)
        if TARGET_MOONSEP != None:
            constraint_gallatitude = MoonSeparationConstraint(min = TARGET_MOONSEP * u.deg, max = None)
            constraint_all.append(constraint_gallatitude)
        return constraint_all
    
    

# %%
if __name__ == '__main__':
    unitnum = 21
    import time
    observer = mainObserver()
    ra = 196.109
    dec = -23.774
    objname = 'GRB 241127A'
    uctime = Time('2025-03-23T05:46:10.144')
    S = SingleTarget(observer = observer, 
                     ra = ra, 
                     dec = dec, 
                     name = objname,
                     exptime = 10,
                     filter_ = 'g',
                     count = 5, 
                     binning=  1, 
                     obsmode ='Spec',
                     specmode = 'specall',
                     colormode = 'gri')
    #S.status
    #S#.staralt()
    #print(time.time() - start)
#%%
