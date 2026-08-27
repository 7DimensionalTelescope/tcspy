#%%
from astropy.time import Time
from astropy.io import fits
import numpy as np

import astropy.units as u
from astropy.visualization import ImageNormalize
from astropy.visualization import ZScaleInterval
from astropy.visualization import LinearStretch
import matplotlib.pyplot as plt 
import os
import re
from tcspy.configuration import mainConfig
from datetime import datetime
#%%
class mainImage(mainConfig):
    """
    A class representing main image information.

    Parameters
    ----------
    frame_number : int
        The frame number of the image.
    config_info : dict
        Configuration information.
    image_info : dict
        Information about the image.
    camera_info : dict, optional
        Information about the camera, by default None.
    mount_info : dict, optional
        Information about the mount, by default None.
    filterwheel_info : dict, optional
        Information about the filterwheel, by default None.
    focuser_info : dict, optional
        Information about the focuser, by default None.
    observer_info : dict, optional
        Information about the observer, by default None.
    target_info : dict, optional
        Information about the target, by default None.
    weather_info : dict, optional
        Information about the weather, by default None.
        
    Methods
    -------
    save()
        Save the image.
    show()
        Display the image.
    """
    
    def __init__(self,
                 frame_number : int,
                 config_info : dict,
                 image_info : dict,
                 camera_info : dict = None,
                 mount_info : dict = None,
                 filterwheel_info : dict = None,
                 focuser_info : dict = None,
                 observer_info : dict = None,
                 target_info : dict = None,
                 weather_info : dict = None
                 ):

        self._framenum = frame_number
        self._configinfo = config_info
        self._imginfo = image_info
        self._caminfo = camera_info
        self._mountinfo = mount_info
        self._filtinfo = filterwheel_info
        self._focusinfo = focuser_info
        self._obsinfo = observer_info
        self._targetinfo = target_info
        self._weatherinfo = weather_info
        self.hdu = fits.PrimaryHDU()
        self._construct_hdu()
        self._construct_header()
    
    def _construct_hdu(self):
        """
        Returns the Header Data Unit (HDU).
        
        Returns
        -------
        fits.PrimaryHDU
            Header Data Unit.
        """
        self.hdu.data = self._imginfo['data']
    
    def _construct_header(self):
        """
        Returns the header of the HDU.
        
        Returns
        -------
        Header
            Header of the image.
        """
        telinfo = self._add_telinfo_to_hdr()
        caminfo = self._add_caminfo_to_hdr()
        focusinfo = self._add_focusinfo_to_hdr()
        filtinfo = self._add_filtwheelinfo_to_hdr()
        imginfo = self._add_imginfo_to_hdr()
        targetinfo = self._add_targetinfo_to_hdr()
        configinfo = self._add_configinfo_to_hdr()
        obsinfo = self._add_obsinfo_to_hdr()
        weatherinfo = self._add_weatinfo_to_hdr()
        all_info = {**telinfo,**caminfo,**focusinfo,**filtinfo,**imginfo,**targetinfo,**configinfo,**obsinfo,**weatherinfo}
        for key, value in all_info.items():
            self.hdu.header[key] = (value['value'],str(value['note']))
    
    @property
    def data(self):
        """
        Returns the data of the HDU.
        
        Returns
        -------
        ndarray
            Data of the image.
        """
        return self.hdu.data
    
    def save(self):
        """
        Save the image.
        
        Returns
        -------
        str
            Filepath where the image is saved.
        """
        filename = self._format_filename()
        foldername = self._format_foldername()
        
        if (self.hdu.header['is_rapidToO'].upper() == 'TRUE') or (self.hdu.header['is_ToO'].upper() == 'TRUE'):
            # Include the ToO target name so each ToO target gets its own folder/tar.
            # This lets the data-transfer notification be matched to the correct ToO alert thread.
            # For tile-matched targets the real ToO target name is stored in NOTE
            # (OBJECT holds the tile id), so prefer NOTE and fall back to OBJECT.
            too_name = str(self.hdu.header.get('NOTE', '') or '').strip()
            if too_name.lower() in ('', 'none', 'nan'):
                too_name = str(self.hdu.header.get('OBJECT', '') or '').strip()
            too_name = too_name.replace(' ', '_')
            if too_name:
                foldername += '_%s' % too_name
            # Disambiguate independent dispatches of the same target (e.g. two
            # rapid-ToO triggers minutes apart) with a short suffix from the
            # target's unique row id (OBJCTID), so they don't collide into one
            # folder/tar and get archived/reported as a single observation.
            too_id = str(self.hdu.header.get('OBJCTID', '') or '').strip()
            if too_id and too_id.lower() not in ('none', 'nan'):
                foldername += '_%s' % too_id[:8]
            foldername += '_ToO'
        if not os.path.isdir(os.path.join(self._configinfo['IMAGE_PATH'], foldername)):
            os.makedirs(os.path.join(self._configinfo['IMAGE_PATH'], foldername))

        filepath = os.path.join(self._configinfo['IMAGE_PATH'], foldername, filename)
        if os.path.exists(filepath):
            filepath = self._configinfo['IMAGE_PATH']+"dup_"+filename
            self.hdu.writeto(filepath, overwrite = False) 
        else:
            self.hdu.writeto(filepath, overwrite = False) 
        
        if self._configinfo['IMAGE_SAVEHEADER']:
            headername = filename.replace(('.%s' %self._configinfo['IMAGE_FORMAT']).lower(), '.head')
            headerpath = os.path.join(self._configinfo['IMAGE_PATH'], foldername, headername)
            with open(headerpath, 'w') as f:
                f.write(self.hdu.header.tostring(sep = '\n'))
        return filepath
    
    def show(self):
        """
        Display the image.
        """
        figsize_x = 4 * self.hdu.header['NAXIS1']/4096
        figsize_y = 4 * self.hdu.header['NAXIS2']/4096
        norm = ImageNormalize(self.data, interval=ZScaleInterval(), stretch=LinearStretch())
        plt.figure(dpi = 300, figsize = (figsize_x, figsize_y))
        plt.imshow(self.data, cmap=plt.cm.gray, norm=norm, interpolation='none')
        plt.colorbar()
    
    def _format_foldername(self):
        format_filename = self._configinfo['FOLDERNAME_FORMAT']
        key_data = dict(self.hdu.header)
        
        dt_ut = Time(key_data['DATE-OBS']).datetime
        dt_ut_12 = (Time(key_data['DATE-OBS']) - 12 * u.hour).datetime
        dt_lt = Time(key_data['DATE-LOC']).datetime
        dt_lt_12 = (Time(key_data['DATE-LOC']) - 12 * u.hour).datetime

        key_data['UTCDATE'] = '%.4d%.2d%.2d' % (dt_ut.year, dt_ut.month, dt_ut.day)
        key_data['LTCDATE'] = '%.4d%.2d%.2d' % (dt_lt.year, dt_lt.month, dt_lt.day)
        
        key_data['UTCDATE_'] = '%.4d_%.2d_%.2d' % (dt_ut.year, dt_ut.month, dt_ut.day)
        key_data['LTCDATE_'] = '%.4d_%.2d_%.2d' % (dt_lt.year, dt_lt.month, dt_lt.day)

        key_data['UTCDATE-'] = '%.4d-%.2d-%.2d' % (dt_ut.year, dt_ut.month, dt_ut.day)
        key_data['LTCDATE-'] = '%.4d-%.2d-%.2d' % (dt_lt.year, dt_lt.month, dt_lt.day)
        
        key_data['UTCDATE12'] = '%.4d%.2d%.2d' % (dt_ut_12.year, dt_ut_12.month, dt_ut_12.day)
        key_data['LTCDATE12'] = '%.4d%.2d%.2d' % (dt_lt_12.year, dt_lt_12.month, dt_lt_12.day)
        
        key_data['UTCDATE12_'] = '%.4d_%.2d_%.2d' % (dt_ut_12.year, dt_ut_12.month, dt_ut_12.day)
        key_data['LTCDATE12_'] = '%.4d_%.2d_%.2d' % (dt_lt_12.year, dt_lt_12.month, dt_lt_12.day)

        key_data['UTCDATE12-'] = '%.4d-%.2d-%.2d' % (dt_ut_12.year, dt_ut_12.month, dt_ut_12.day)
        key_data['LTCDATE12-'] = '%.4d-%.2d-%.2d' % (dt_lt_12.year, dt_lt_12.month, dt_lt_12.day)

        key_dict = dict()
        for key in key_data.keys():
            key_dict[key] = str(key_data[key])
        
        def replace_placeholder(match):
            key = match.group(1)
            return key_dict.get(key, match.group(0))
        
        # Use regular expressions to find and replace the placeholders
        pattern = r'\$\$(.*?)\$\$'
        output_string = re.sub(pattern, replace_placeholder, format_filename)
        return output_string
    
    def _format_filename(self):
        format_filename = self._configinfo['FILENAME_FORMAT']
        key_data = dict(self.hdu.header)
        
        key_data['FRAMENUM'] = '%.4d' %(self._framenum)
        
        dt_ut = Time(key_data['DATE-OBS']).datetime
        dt_lt = Time(key_data['DATE-LOC']).datetime
        key_data['UTCDATE'] = '%.4d%.2d%.2d' % (dt_ut.year, dt_ut.month, dt_ut.day)
        key_data['LTCDATE'] = '%.4d%.2d%.2d' % (dt_lt.year, dt_lt.month, dt_lt.day)
        key_data['UTCTIME'] = '%.2d%.2d%.2d' % (dt_ut.hour, dt_ut.minute, dt_ut.second)
        key_data['LTCTIME'] = '%.2d%.2d%.2d' % (dt_lt.hour, dt_lt.minute, dt_lt.second)
        
        key_data['UTCDATE_'] = '%.4d_%.2d_%.2d' % (dt_ut.year, dt_ut.month, dt_ut.day)
        key_data['LTCDATE_'] = '%.4d_%.2d_%.2d' % (dt_lt.year, dt_lt.month, dt_lt.day)
        key_data['UTCTIME_'] = '%.2d_%.2d_%.2d' % (dt_ut.hour, dt_ut.minute, dt_ut.second)
        key_data['LTCTIME_'] = '%.2d_%.2d_%.2d' % (dt_lt.hour, dt_lt.minute, dt_lt.second)
        
        key_data['UTCDATE-'] = '%.4d-%.2d-%.2d' % (dt_ut.year, dt_ut.month, dt_ut.day)
        key_data['LTCDATE-'] = '%.4d-%.2d-%.2d' % (dt_lt.year, dt_lt.month, dt_lt.day)
        key_data['UTCTIME-'] = '%.2d-%.2d-%.2d' % (dt_ut.hour, dt_ut.minute, dt_ut.second)
        key_data['LTCTIME-'] = '%.2d-%.2d-%.2d' % (dt_lt.hour, dt_lt.minute, dt_lt.second)
        
        key_dict = dict()
        for key in key_data.keys():
            key_dict[key] = str(key_data[key])
            
        
        def replace_placeholder(match):
            key = match.group(1)
            return key_dict.get(key, match.group(0))

        # Use regular expressions to find and replace the placeholders
        pattern = r'\$\$(.*?)\$\$'
        output_string = re.sub(pattern, replace_placeholder, format_filename)
        output_string += ('.%s' %self._configinfo['IMAGE_FORMAT']).lower()
        return output_string
    
    def _format_header(self,
                       value,
                       note : str = ''):
        return dict(value = value, note=  note)
        
    def _add_configinfo_to_hdr(self):
        
        info = dict()
        # telescope
        info['MNT_IP'] = self._format_header(self._configinfo['MOUNT_HOSTIP'],'Hosting IP for TCSpy mount device')
        info['MNT_PRT'] =self._format_header(self._configinfo['MOUNT_PORTNUM'],'Port number of TCSpy mount device')
        info['MNT_NUM'] = self._format_header(self._configinfo['MOUNT_DEVICENUM'],'Device number of TCSpy mount device')
        info['FOCALLEN'] = self._format_header(self._configinfo['MOUNT_FOCALLENGTH'],'[mm] Focal length of the telescope')
        info['FOCALRAT'] = self._format_header(self._configinfo['MOUNT_FOCALRATIO'],'[mm] Focal length of the telescope')
        info['APTDIA'] = self._format_header(self._configinfo['MOUNT_DIAMETER'], '[m] Diameter of the telescope')
        info['APTAREA'] = self._format_header(1e4*np.pi*(float(self._configinfo['MOUNT_DIAMETER'])/2)**2, '[mm^2] Aperture area of the telescope')
        info['TELESCOP'] = self._format_header(self._configinfo['MOUNT_NAME'], 'Name of the telescope')

        # camera
        info['CAM_IP'] = self._format_header(self._configinfo['CAMERA_HOSTIP'],'Hosting IP for ALPACA camera device')
        info['CAM_PRT'] = self._format_header(self._configinfo['CAMERA_PORTNUM'],'Port number of ALPACA camera device')
        info['CAM_NUM'] = self._format_header(self._configinfo['CAMERA_DEVICENUM'],'Device number of ALPACA camera device')
        info['XPIXSZ'] = self._format_header(self._configinfo['CAMERA_PIXSIZE'], '[um] Pixel width')
        info['YPIXSZ'] = self._format_header(self._configinfo['CAMERA_PIXSIZE'], '[um] Pixel height')
        # filterwheel 
        info['FILT_IP'] = self._format_header(self._configinfo['FTWHEEL_HOSTIP'],'Hosting IP for ALPACA filterwheel device')
        info['FILT_PRT'] = self._format_header(self._configinfo['FTWHEEL_PORTNUM'],'Port number of ALPACA filterwheel device')
        info['FILT_NUM'] = self._format_header(self._configinfo['FTWHEEL_DEVICENUM'],'Device number of ALPACA filterwheel device')
        # focuser
        info['FOC_IP'] = self._format_header(self._configinfo['FOCUSER_HOSTIP'],'Hosting IP for ALPACA focuser device')
        info['FOC_PRT'] = self._format_header(self._configinfo['FOCUSER_PORTNUM'],'Port number of ALPACA focuser device')
        info['FOC_NUM'] = self._format_header(self._configinfo['FOCUSER_DEVICENUM'],'Device number of ALPACA focuser device')
        # weather
        info['WTER_IP'] = self._format_header(self._configinfo['WEATHER_HOSTIP'],'Hosting IP for ALPACA weather device')
        info['WTER_PRT'] = self._format_header(self._configinfo['WEATHER_PORTNUM'],'Port number of ALPACA weather device')
        info['WTER_NUM'] = self._format_header(self._configinfo['WEATHER_DEVICENUM'],'Device number of ALPACA weather device')
        # safetymonitor
        info['SAFE_IP'] = self._format_header(self._configinfo['SAFEMONITOR_HOSTIP'],'Hosting IP for ALPACA weather device')
        info['SAFE_PRT'] = self._format_header(self._configinfo['SAFEMONITOR_PORTNUM'],'Port number of ALPACA weather device')
        info['SAFE_NUM'] = self._format_header(self._configinfo['SAFEMONITOR_DEVICENUM'],'Device number of ALPACA weather device')
        # logger
        info['LOGPATH'] = self._format_header(self._configinfo['LOGGER_PATH'], 'Log file path')######################3
        return info
    
    def _add_weatinfo_to_hdr(self):
        info = dict()
        info['DATE-WEA'] = None
        info['AMBTEMP'] = None
        info['HUMIDITY'] = None
        info['PRESSURE'] = None
        info['DEWPOINT'] = None
        info['WINDSPED'] = None
        info['WINDDIR'] = None
        info['WINDGUST'] = None
        info['SKYBRGHT'] = None
        info['SKYTEMP'] = None
        info['SKYFWHM'] = None
        info['CLUDFRAC'] = None
        info['RAINRATE'] = None

        if self._weatherinfo:
            info['DATE-WEA'] = self._format_header(self._weatherinfo['update_time'], '[UTC] UTC of the latest weather update')
            info['AMBTEMP'] = self._format_header(self._weatherinfo['temperature'], '[deg C] Ambient temperature at the observatory')
            info['HUMIDITY'] = self._format_header(self._weatherinfo['humidity'], '[%] Atmospheric relative humidity at the observatory')
            info['PRESSURE'] = self._format_header(self._weatherinfo['pressure'], '[hPa] Atmospheric pressure at the observatory altitude')
            info['DEWPOINT'] = self._format_header(self._weatherinfo['dewpoint'], '[deg C] Atmospheric dew point temperature at the observatory')
            info['WINDSPED'] = self._format_header(self._weatherinfo['windspeed'], '[m/s] Wind speed at the observatory')
            info['WINDDIR'] = self._format_header(self._weatherinfo['winddirection'], '[deg] Wind direction: 0=N, 90 = E, 180=S, 270=W')
            info['WINDGUST'] = self._format_header(self._weatherinfo['windgust'], '[m/s] Peak 3 second wind gust (m/s) at the observatory over the last 2 minutes')
            info['SKYBRGHT'] = self._format_header(self._weatherinfo['skybrightness'], '[mag/arcsec^2] Sky quality at the observatory')
            info['SKYTEMP'] = self._format_header(self._weatherinfo['skytemperature'], '[deg C] Sky temperature at the observatory')
            info['SKYFWHM'] = self._format_header(self._weatherinfo['fwhm'], '[arcsec] Seeing at the observatory')
            info['CLUDFRAC'] = self._format_header(self._weatherinfo['cloudfraction'], '[%] Amount of sky obscured by cloud')
            info['RAINRATE'] = self._format_header(self._weatherinfo['rainrate'], '[mm/hr] Rain rate at the observatory')
        return info
    
    def _add_caminfo_to_hdr(self):
        info = dict()
        info['INSTRUME'] = None
        info['EGAIN'] = None
        info['CCD-TEMP'] = None
        info['SET-TEMP'] = None
        info['COLPOWER'] = None
        if self._caminfo:
            info['INSTRUME'] = self._format_header(self._caminfo['name_cam'], 'Detector instrument name')
            info['GAIN'] = self._format_header(self._caminfo['gain'], 'Gain from the camera configuration')
            info['EGAIN'] = self._format_header(self._caminfo['egain'], '[e-/ADU] Eletrconic gain')
            info['CCD-TEMP'] = self._format_header(self._caminfo['ccdtemp'], '[deg C] CCD temperature')
            info['SET-TEMP'] = self._format_header(self._caminfo['set_ccdtemp'], '[deg C] CCD temperature setpoint')
            info['COLPOWER'] = self._format_header(self._caminfo['power_cooler'], '[%] CCD cooler power')
        return info
    
    def _add_telinfo_to_hdr(self):
        info = dict()
        info['ALTITUDE'] = None
        info['AZIMUTH'] = None
        info['CENTALT'] = None
        info['CENTAZ'] = None
        info['RA'] = None
        info['DEC'] = None
        info['AIRMASS'] = None
        if self._mountinfo:
            altitude = float(self._mountinfo['alt'])
            airmass = 1/np.sin(np.deg2rad((altitude) + 244/(165+47*(altitude)**1.1))) # Pickering 2002
            info['AIRMASS'] = self._format_header(airmass, 'Airmass at frame center (Pickering 2002) ')
            info['ALTITUDE'] = self._format_header(altitude, '[deg] Altitude of the telescope pointing')
            info['AZIMUTH'] = self._format_header(float(self._mountinfo['az']), '[deg] Azimuth of the telescope pointing')
            info['CENTALT'] = self._format_header(altitude, '[deg] Altitude of the telescope pointing')
            info['CENTAZ'] = self._format_header(float(self._mountinfo['az']), '[deg] Azimuth of the telescope pointing')
            info['RA'] = self._format_header(float(self._mountinfo['ra']), '[deg] Right ascension of the telescope pointing')
            info['DEC'] = self._format_header(float(self._mountinfo['dec']), '[deg] Declination of the telescope pointing')
        return info
        
    def _add_filtwheelinfo_to_hdr(self):
        info = dict()
        info['FILTER'] = None
        if self._filtinfo:
            info['FILTER'] = self._format_header(self._filtinfo['filter_'], 'Name of the filter')
        return info

    def _add_focusinfo_to_hdr(self):
        info = dict()
        info['FOCUSPOS'] = None
        if self._focusinfo:
            info['FOCUSPOS'] = self._format_header(self._focusinfo['position'], 'Position of the focuser')
        return info
    
    def _add_obsinfo_to_hdr(self):
        info = dict()
        info['OBSERVER'] = None
        info['SITELAT'] = None
        info['SITELONG'] = None
        info['SITEELEV'] = None
        info['MOONPHAS'] = None
        if self._obsinfo:
            info['OBSERVER'] = self._format_header(self._obsinfo['name_observer'], 'Name of the observer') 
            info['SITELAT'] = self._format_header(self._obsinfo['latitude'], '[deg] Latitude of the observatory') 
            info['SITELONG'] = self._format_header(self._obsinfo['longitude'], '[deg] Longitude of the observatory') 
            info['SITEELEV'] = self._format_header(self._obsinfo['elevation'], '[m] Elevation of the observatory')
            info['MOONPHAS'] = self._format_header(self._obsinfo['moonphase'], '[0-1] Illuminated fraction of the moon (0=new, 1=full)')
        return info
    
    def _add_imginfo_to_hdr(self):
        info = dict()
        info['IMAGETYP'] = self._format_header(self._imginfo['imgtype'], 'Type of the image')
        info['EXPTIME'] = self._format_header(self._imginfo['exptime'], '[seconds] Duration of exposure time')
        info['EXPOSURE'] = self._format_header(self._imginfo['exptime'], '[seconds] Duration of exposure time')
        info['DATE-OBS'] = self._format_header(self._imginfo['date_obs_utc'], '[UTC] Date of the observation')
        info['DATE-LOC'] = self._format_header(self._imginfo['date_obs_ltc'], '[LTC] Date of the observation')
        info['JD'] = self._format_header(self._imginfo['jd'], '[JD] Julian date')
        info['MJD'] = self._format_header(self._imginfo['mjd'], '[MJD] Modified Julian date')
        info['XBINNING'] = self._format_header(self._imginfo['binningX'], 'Binning level along the X-axis')
        info['YBINNING'] = self._format_header(self._imginfo['binningY'], 'Binning level along the Y-axis')
        return info
    
    def _add_targetinfo_to_hdr(self):
        info = dict()
        info['OBJECT'] = None
        info['OBJTYPE'] = None
        info['OBJCTRA'] = None
        info['OBJCTDEC'] = None
        info['OBJCTRA_'] = None
        info['OBJCTDE_'] = None
        info['OBJCTALT'] = None
        info['OBJCTAZ'] = None
        info['OBJCTHA'] = None
        info['OBJCTID'] = None
        info['MOONSEP'] = None
        info['OBSMODE'] = None
        info['SPECMODE'] = None
        info['NTELSCOP'] = None
        info['NOTE'] = None
        info['is_ToO'] = None
        info['is_rapidToO'] = None
        if self._targetinfo:
            info['OBJECT'] = self._format_header(self._targetinfo['name'], 'Name of the target')            
            info['OBJTYPE'] = self._format_header(self._targetinfo['objtype'], 'Type of the target')
            info['OBJCTRA'] = self._format_header(self._targetinfo['ra_hour_hms'], '[h m s] Right ascension of the target in hms format')
            info['OBJCTDEC'] = self._format_header(self._targetinfo['dec_deg_dms'], '[d m s] Declination of the target in dms format')
            info['OBJCTRA_'] = self._format_header(self._targetinfo['ra'], '[deg] Right ascension of the target in deg')
            info['OBJCTDE_'] = self._format_header(self._targetinfo['dec'], '[deg] Declination of the target in deg')
            info['OBJCTALT'] = self._format_header(self._targetinfo['alt'], '[deg] Altitude of the target')
            info['OBJCTAZ'] = self._format_header(self._targetinfo['az'], '[deg] Azimuth of the target')
            info['OBJCTHA'] = self._format_header(self._targetinfo['hourangle'], '[h m s] Hourangle of the target')
            info['OBJCTID'] = self._format_header(self._targetinfo['id_'], 'ID of the target')
            info['MOONSEP'] = self._format_header(self._targetinfo['moonsep'], '[deg] Separation angle between the target and the moon')
            info['OBSMODE'] = self._format_header(self._targetinfo['obsmode'], 'Observation mode')
            info['SPECMODE'] = self._format_header(self._targetinfo['specmode'], 'Specmode (when OBSMODE == "SPEC")')
            info['NTELSCOP'] = self._format_header(self._targetinfo['ntelescope'], 'Number of telescopes involved in the observation')
            info['NOTE'] = self._format_header(self._targetinfo['note'], 'Note of the target')
            is_ToO_str = str(True) if self._targetinfo['is_ToO'] else str(False)
            info['is_ToO'] = self._format_header(is_ToO_str, 'Is the target a ToO?')
            is_rapidToO_str = str(True) if self._targetinfo['is_rapidToO'] else str(False)
            info['is_rapidToO'] = self._format_header(is_rapidToO_str, 'Is the target a rapid ToO?')
        return info


# %%
