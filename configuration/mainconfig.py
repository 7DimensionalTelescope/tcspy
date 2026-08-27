
# Written by Hyeonho Choi 2023.01
# %%
import glob
import os
from astropy.io import ascii
import json

class mainConfig:
    def __init__(self,
                 unitnum: int = None,
                 configpath : str = f'{os.path.dirname(os.path.abspath(__file__))}',
                 **kwargs):
        self.unitnum = unitnum
        self.config = dict()
                
        # global config params
        self.path_global = configpath
        self.path_home = os.path.expanduser('~')
        self._configfilekey_global = os.path.join(self.path_global, '*.config')
        self._configfiles_global = glob.glob(self._configfilekey_global)
            
        if not os.path.isfile(os.path.join(self.path_global, 'TCSpy.config')):
            self.make_configfile(self.tcspy_params, filename='TCSpy.config', savepath= self.path_global)
            raise RuntimeError(f'TCSpy.config must be located in the configuration folder. \n New TCSpy.config file is created: {os.path.join(self.path_global, "TCSpy.config")} ')
        else:
            config_global = self._load_configuration(self._configfiles_global)
            self.config.update(config_global)
        
        if self.unitnum:
            # Specified units config params
            self.tel_name = self.config["TCSPY_TEL_NAME"] + '%.2d' % self.unitnum
            self.path_unit = os.path.join(configpath, self.tel_name)
            self._configfilekey_unit = os.path.join(self.path_unit, '*.config')
            self._configfiles_unit = glob.glob(self._configfilekey_unit)
            if len(self._configfiles_unit) == 0:
                print('No configuration file is found.\nTo make default configuration files, run tcspy.configuration.make_config')
            else:
                config_unit = self._load_configuration(self._configfiles_unit)
                self.config.update(config_unit)

    def _load_configuration(self, 
                            configfiles):
        all_config = dict()
        for configfile in configfiles:
            with open(configfile, 'r') as f:
                config = json.load(f)
                all_config.update(config)
        return all_config

    def make_configfile(self, 
                        dict_params : dict,
                        filename: str,
                        savepath : str):
        filepath = os.path.join(savepath, filename)
        with open(filepath, 'w') as f:
            json.dump(dict_params, f, indent=4)
        print('New configuration file made : %s' % (filepath))
        
    @property
    def tcspy_params(self):
        tcspy_params = dict(TCSPY_VERSION='Version 1.0',
                            TCSPY_TEL_NAME='7DT')           
        return tcspy_params

    def _initialize_config(self,
                           ip_address: str = '10.0.106.6',
                           portnum : int = '11111',
                           update_focusmodel : bool = True,
                           **kwargs):
        savepath_unit = self.path_unit
        if not os.path.exists(savepath_unit):
            os.makedirs(savepath_unit, exist_ok=True)
            
        ###### ALL CONFIGURATION PARAMETERS(EDIT HERE!!!) #####
        mount_params = dict(MOUNT_DEVICETYPE='PWI4',  # Alpaca or PWI4
                            MOUNT_HOSTIP= ip_address,
                            MOUNT_PORTNUM='8220',
                            MOUNT_DEVICENUM=0,
                            MOUNT_PARKALT=40,
                            MOUNT_PARKAZ=300,
                            MOUNT_RMSRA=0.15,
                            MOUNT_RMSDEC=0.15,
                            MOUNT_CHECKTIME=0.5,
                            MOUNT_DIAMETER=0.5,
                            MOUNT_APAREA=0.196,
                            MOUNT_FOCALLENGTH=1537.0,
                            MOUNT_FOCALRATIO=3,
                            MOUNT_SETTLETIME=3, #seconds
                            MOUNT_NAME= self.tel_name
                            )
        camera_params = dict(CAMERA_HOSTIP= ip_address,
                             CAMERA_PORTNUM=portnum,
                             CAMERA_DEVICENUM=0,
                             CAMERA_PIXSIZE=9,  # micron
                             CAMERA_CHECKTIME=0.5)
                             
        filterwheel_params = dict(FTWHEEL_HOSTIP= ip_address,
                                  FTWHEEL_PORTNUM=portnum,
                                  FTWHEEL_DEVICENUM=0,
                                  FTWHEEL_CHECKTIME=0.5,
                                  FTWHEEL_OFFSETFILE =f"{os.path.join(savepath_unit,'filter.offset')}")

        focuser_params = dict(FOCUSER_DEVICETYPE='NINA',  # Alpaca or PWI4
                              FOCUSER_HOSTIP= ip_address,
                              FOCUSER_PORTNUM='8220',
                              FOCUSER_DEVICENUM=0,
                              FOCUSER_MINSTEP= 2000,
                              FOCUSER_MAXSTEP= 14000,
                              FOCUSER_CHECKTIME=0.5)
        
        switch_params = dict(SWITCH_HOSTIP= ip_address,
                             SWITCH_PORTNUM=portnum,
                             SWITCH_DEVICENUM = 0,
                             SWITCH_TYPES = ['MOUNT', 'FOCUSER', 'CAMERA'],
                             SWITCH_KEY_MOUNT = 'MOUNT',
                             SWITCH_KEY_FOCUSER = 'FOCUS',
                             SWITCH_KEY_CAMERA = 'CAM',
                             SWITCH_KEY_FILTERWHEEL = 'CAM')
        
        observer_params = dict(OBSERVER_LONGITUDE= -70.7804,
                               OBSERVER_LATITUDE= -30.4704,
                               OBSERVER_ELEVATION= 1580,
                               OBSERVER_TIMEZONE= 'America/Santiago',
                               OBSERVER_NAME='YoungPyo Hong'
                               )
        
        image_params = dict(FOLDERNAME_FORMAT = "$$UTCDATE12-$$_gain$$GAIN$$",
                            FILENAME_FORMAT= "$$TELESCOP$$_$$UTCDATE$$_$$UTCTIME$$_$$OBJECT$$_$$FILTER$$_$$XBINNING$$x$$YBINNING$$_$$EXPTIME$$s_$$FRAMENUM$$",
                            IMAGE_PATH=f'/data2/obsdata/{self.tel_name}/image/',
                            IMAGE_SAVEHEADER = True,
                            IMAGE_FORMAT = 'FITS'
                            )
        
        logger_params = dict(LOGGER_SAVE=True,
                             LOGGER_LEVEL='INFO', 
                             LOGGER_FORMAT=f'[%(levelname)s,{self.tel_name}]%(asctime)-15s |%(message)s',
                             LOGGER_PATH= f'/data2/obsdata/{self.tel_name}/log/')
        
        # Share configuration

        transfer_params = dict(TRANSFER_SERVER_IP= '210.117.217.71',
                               TRANSFER_SERVER_USERNAME = 'hhchoi1022', 
                               TRANSFER_SERVER_PORTNUM = '8022',
                               TRANSFER_SOURCE_HOMEDIR = '/data2/obsdata/',
                               TRANSFER_ARCHIVE_HOMEDIR = '/data1/obsdata_archive/',
                               TRANSFER_SERVER_HOMEDIR = '/data/data1/obsdata/obsdata_from_mcs/',
                               TRANSFER_SYNC = f'{os.path.join(self.path_home,".tcspy", "sync","transfer.txt")}',
                               TRANSFER_GRIDFTP_NUMPARALLEL = 32,
                               TRANSFER_GRIPFTP_VERBOSE = True,
                               TRANSFER_GRIDFTP_RETRIES = 30,
                               TRANSFER_GRIDFTP_RTINTERVAL = 60
                               )
        
        weather_params = dict(WEATHER_HOSTIP= '10.0.11.3',#ip_address, #'10.0.11.3'
                              WEATHER_PORTNUM= 5575,#portnum, #5575
                              WEATHER_DEVICENUM=0,
                              WEATHER_UPDATETIME=60,
                              WEATHER_PATH= f'/data2/obsdata/weather_history/',
                              WEATHER_STATUSPATH = f'{os.path.join(self.path_home,".tcspy", "sync")}',
                              WEATHER_HUMIDITY=85,
                              WEATHER_RAINRATE=80,
                              WEATHER_SKYMAG=10,
                              WEATHER_TEMPERATURE_UPPER=-25,
                              WEATHER_TEMPERATURE_LOWER=40,
                              WEATHER_WINDSPEED=20)

        dome_params = dict(DOME_HOSTIP= ip_address,
                           DOME_PORTNUM=portnum,
                           DOME_DEVICENUM=0,
                           DOME_CHECKTIME=0.5)
        
        safetymonitor_params = dict(SAFEMONITOR_HOSTIP= '10.0.11.3', #ip_address, #'10.0.11.3'
                                    SAFEMONITOR_PORTNUM= 5565,#portnum, #5565
                                    SAFEMONITOR_DEVICENUM=0,
                                    SAFEMONITOR_UPDATETIME=60,
                                    SAFEMONITOR_PATH= f'/data2/obsdata/safetymonitor_history/')
        
        target_params = dict(TARGET_MINALT=25,
                             TARGET_MAXALT=90,
                             TARGET_MOONSEP=40,
                             TARGET_WEIGHT_ALT = 0.5,
                             TARGET_WEIGHT_PRIORITY = 0.5)

        DB_params = dict(DB_HOSTIP='localhost',
                         DB_ID='hhchoi',
                         DB_PWD='gusgh1020!', # gusgh1020! for MCS, lksdf1020 for Lnx
                         DB_NAME='target',
                         DB_HISTORYPATH= f'/data2/obsdata/DB_history',
                         DB_HISTORYFORMAT = 'ascii.fixed_width',
                         DB_STATUSPATH = f'{os.path.join(self.path_home,".tcspy", "sync")}',
                         DB_STATUSFORMAT = 'ascii')
        
        gmail_params = dict(GMAIL_USERNAME= '7dt.observation.alert@gmail.com',
                            GMAIL_TOKENPATH = os.path.join(self.path_home, '.tcspy', f'gmail/python/token_7dt.observation.alert@gmail.com.txt')
                            )
        
        slack_params = dict(SLACK_TOKEN = os.path.join(self.path_home, '.tcspy', f'slack/slack_token_7dt_obseration_alert.txt'),
                            SLACK_DEFAULT_CHANNEL = 'C0AUD37DQG5',
                            SLACK_ALERT_CHANNEL = 'C0AUD37DQG5')
        
        googlesheet_params = dict(GOOGLESHEET_URL = 'https://docs.google.com/spreadsheets/d/1UorU7P_UMr22Luw6q6GLQYk4-YicGRATwCePRxkx2Ms/edit#gid=0',
                                  GOOGLESHEET_AUTH = os.path.join(self.path_home, '.tcspy', f'googlesheet/targetdb-423908-ee7bb8c14ff3.json'),
                                  GOOGLESHEET_SCOPE = ['https://spreadsheets.google.com/feeds',
                                                       'https://www.googleapis.com/auth/drive',
                                                       'https://www.googleapis.com/auth/spreadsheets'])
        
        alertbroker_params = dict(ALERTBROKER_AUTHUSERS = ['hhchoi1022@gmail.com',
                                                           'jhkim.astrosnu@gmail.com', # Ji hoon Kim
                                                           'myungshin.im@gmail.com',  # Myungshin Im
                                                           'takdg123@gmail.com',
                                                           'seowon.chang@gmail.com',
                                                           'gregorypaek94@gmail.com',
                                                           ''
                                                           ],
                                  ALERTBROKER_NORMUSERS = ['hhchoi1022@snu.ac.kr' # Hyeonho Choi (2)
                                                           ],
                                  ALERTBROKER_ADMINUSERS = ['hhchoi1022@gmail.com'], # Hyeonho Choi
                                  ALERTBROKER_PATH = f'/data2/obsdata/alert_history',
                                  ALERTBROKER_STATUSPATH = f'{os.path.join(self.path_home, ".tcspy", "sync", "alert")}',
                                )
        
        autofocus_params = dict(AUTOFOCUS_FILTINFO_FILE=f'{os.path.join(self.path_home, ".tcspy", "sync", "filtinfo.dict")}',
                                AUTOFOCUS_FOCUSHISTORY_PATH = self.path_global,
                                AUTOFOCUS_TOLERANCE = 45)
        
        autoflat_params = dict(AUTOFLAT_ALTITUDE = 40,
                               AUTOFLAT_AZIMUTH = 270,
                               AUTOFLAT_MINCOUNT = 20000,
                               AUTOFLAT_MAXCOUNT = 40000,
                               AUTOFLAT_MINEXPTIME = 0.1,
                               AUTOFLAT_MAXEXPTIME = 20,
                               AUTOFLAT_WAITDURATION = 10,
                               AUTOFLAT_FILTERORDER = ['g','r','i','m500','m525','m550','m575','m475','m450','m600','m625','m650','m675','m425','m700','m725','z','m400','m375w','m750','m775','m800','m825','m850','m875','u'] # Descending order (Brightest first)
                               )
        
        specmode_params = dict(SPECMODE_FOLDER=f'{os.path.join(self.path_home, ".tcspy", "sync","specmode/20250313/")}')

        colormode_params = dict(COLORMODE_FOLDER=f'{os.path.join(self.path_home, ".tcspy", "sync","colormode/20250313/")}')
        
        startup_params = dict(STARTUP_ALT = 30,
                              STARTUP_AZ = 90,
                              STARTUP_CCDTEMP = -10,
                              STARTUP_CCDTEMP_TOLERANCE = 1)

        shutdown_params = dict(SHUTDOWN_ALT = 30,
                               SHUTDOWN_AZ = 90,
                               SHUTDOWN_CCDTEMP = 10,
                               SHUTDOWN_CCDTEMP_TOLERANCE = 1)
        
        nightsession_params = dict(NIGHTSESSION_SUNALT_AUTOFLAT = -8,
                                   NIGHTSESSION_SUNALT_STARTUP = -6,
                                   NIGHTSESSION_SUNALT_OBSERVATION = -15,
                                   NIGHTSESSION_SUNALT_SHUTDOWN = 10)
        
        multitelescopes_params = dict(MULTITELESCOPES_FILE = f'{os.path.join(self.path_home, ".tcspy", "sync", "multitelescopes.dict")}')
        
        nightobs_params = dict(NIGHTOBS_SAFETYPE = 'safetymonitor',)        
        
        appscheduler_params = dict(APPSCHEDULER_AUTOBIAS = True,
                                   APPSCHEDULER_AUTODARK = True,
                                   APPSCHEDULER_AUTOFLAT = True,
                                   APPSCHEDULER_SEARCHKEY = '/data2/obsdata/7DT??/image/$$TONIGHT$$/*.fits',
                                   )
        self.make_configfile(mount_params, filename='mount.config', savepath = savepath_unit)
        self.make_configfile(camera_params, filename='camera.config', savepath = savepath_unit)
        self.make_configfile(filterwheel_params, filename='filterWheel.config', savepath = savepath_unit)
        self.make_configfile(focuser_params, filename='focuser.config', savepath = savepath_unit)
        self.make_configfile(logger_params, filename='logger.config', savepath = savepath_unit)
        self.make_configfile(image_params, filename='image.config', savepath = savepath_unit)
        self.make_configfile(switch_params, filename='switch.config', savepath = savepath_unit)
        
        # Global params
        self.make_configfile(gmail_params, filename='gmail.config', savepath= self.path_global)
        self.make_configfile(slack_params, filename='slack.config', savepath= self.path_global)
        self.make_configfile(googlesheet_params, filename='googleSheet.config', savepath= self.path_global)
        self.make_configfile(alertbroker_params, filename='alertbroker.config', savepath= self.path_global)
        self.make_configfile(self.tcspy_params, filename='TCSpy.config', savepath= self.path_global)
        self.make_configfile(observer_params, filename='observer.config', savepath= self.path_global)
        self.make_configfile(target_params, filename='target.config', savepath= self.path_global)
        self.make_configfile(transfer_params, filename='transfer.config', savepath= self.path_global)
        
        self.make_configfile(weather_params, filename='weather.config', savepath= self.path_global)
        self.make_configfile(dome_params, filename='dome.config', savepath= self.path_global)
        self.make_configfile(safetymonitor_params, filename='safetymonitor.config', savepath= self.path_global)
        self.make_configfile(DB_params, filename = 'db.config', savepath= self.path_global)
        self.make_configfile(autofocus_params, filename = 'autofocus.config', savepath= self.path_global)
        self.make_configfile(autoflat_params, filename = 'autoflat.config', savepath= self.path_global)
        self.make_configfile(specmode_params, filename = 'specmode.config', savepath= self.path_global)
        self.make_configfile(colormode_params, filename = 'colormode.config', savepath= self.path_global)
        self.make_configfile(startup_params, filename = 'startup.config', savepath= self.path_global)
        self.make_configfile(shutdown_params, filename = 'shutdown.config', savepath= self.path_global)
        self.make_configfile(nightobs_params, filename = 'nightobs.config', savepath= self.path_global)
        self.make_configfile(nightsession_params, filename = 'nightsession.config', savepath= self.path_global)
        self.make_configfile(multitelescopes_params, filename = 'multitelescopes.config', savepath= self.path_global)
        self.make_configfile(appscheduler_params, filename = 'appscheduler.config', savepath= self.path_global)
        
        os.makedirs(image_params['IMAGE_PATH'], exist_ok=True)
        os.makedirs(logger_params['LOGGER_PATH'], exist_ok=True)
        
        if update_focusmodel:
            from tcspy.configuration import FocusModel
            F = FocusModel(unitnum = self.unitnum, configpath = self.path_global, filtinfo_file = f'{os.path.join(self.path_home, ".tcspy", "sync", "filtinfo.dict")}', offset_file = "filter.offset")
            F.update_params()
        



#%%
if __name__ == '__main__':
    unitnumlist = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]
    addresslist = ['10.0.106.6',
                   '10.0.106.7',
                   '10.0.106.8',
                   '10.0.106.16',
                   '10.0.106.10',
                   '10.0.106.11',
                   '10.0.106.12',
                   '10.0.106.13',
                   '10.0.106.14',
                   '10.0.106.15',
                   '10.0.106.9',
                   '10.0.106.17',
                   '10.0.106.18',
                   '10.0.106.19',
                   '10.0.106.20',
                   '10.0.106.21']
    for unitnum, address in zip(unitnumlist, addresslist):
        A = mainConfig(unitnum=unitnum)
        A._initialize_config(ip_address=address, portnum = 11111, update_focusmodel = True, calc_focusmodel = False)

# %%
if __name__ == '__main__':
    unitnumlist = [21]
    addresslist = ['127.0.0.1']
    for unitnum, address in zip(unitnumlist, addresslist):
        A = mainConfig(unitnum=unitnum)
        A._initialize_config(ip_address=address, portnum = 32323)
# %%
