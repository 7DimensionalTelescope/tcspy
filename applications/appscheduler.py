#%%
import signal
from tcspy.configuration import mainConfig
from tcspy.devices import SingleTelescope
from tcspy.devices import MultiTelescopes
from tcspy.utils import NightSession
from tcspy.utils.connector import SlackConnector
from tcspy.applications import BiasAcquisition
from tcspy.applications import DarkAcquisition
from tcspy.applications import NightObservation
from tcspy.applications import FilterCheck
from tcspy.applications import Startup
from tcspy.applications import Shutdown
from tcspy.applications import FlatAcquisition
from tcspy.utils.databases import DB_Dynamic
from tcspy.utils.databases import DB
from tcspy.utils import DataTransferManager

from ccdproc import ImageFileCollection
from threading import Event
import astropy.units as u
from astropy.time import Time
import numpy as np
import uuid
import time
import threading
import schedule
import json
import re
import glob
import os
import warnings
from astropy.coordinates.baseframe import NonRotationTransformationWarning

# Ignore the specific astropy warning globally
warnings.filterwarnings('ignore', category=NonRotationTransformationWarning)
#%%
class AppScheduler(mainConfig):
    
    def __init__(self,
                 multitelescopes : MultiTelescopes,
                 abort_action : Event,
                 ):
        super().__init__()
        self.multitelescopes = multitelescopes
        self._set_obsnight()
        self.slack_alert_sender = None
        self.slack_message_ts = None
        self.schedule = schedule
        self.thread_lock = threading.Lock()
        self.abort_action = abort_action

    def get_obsinfo_tonight(self, tonight_str, return_only_set : bool = True, key_for_set : list = ['exptime', 'xbinning', 'gain']):
        """
        Get all observation configurations
        """
            
        def load_collection(file_pattern, return_only_light = True):
            from astropy.table import Table, vstack
            
            # Define file search pattern
            all_files = glob.glob(file_pattern)
            if len(all_files) == 0:
                print(f"Warning: No FITS files found with pattern '{file_pattern}'")
                return None

            # Get unique parent directories
            directories = list(set(os.path.dirname(file) for file in all_files))
            
            # Initialize an empty list to store all file paths
            all_coll = Table()

            # Iterate through directories and collect FITS file paths
            for directory in directories:
                coll = ImageFileCollection(location=directory, glob_include='*.fits')
                if len(coll.files) > 0:
                    print(f"Loaded {len(coll.files)} FITS files from {directory}")

                    # Convert summary table to a uniform format
                    summary = coll.summary.copy()

                    # Ensure all string columns are explicitly converted to `str`
                    for colname in summary.colnames:
                        col_dtype = summary[colname].dtype
                        if col_dtype.kind in ('O', 'U', 'S'):  # Object, Unicode, or String types
                            summary[colname] = summary[colname].astype(str)
                        elif col_dtype.kind in ('i', 'f'):  # Integer or Float types
                            summary[colname] = summary[colname].astype(str)  # Convert to string for consistency
                            summary[colname].fill_value = ''  # Ensure NaN values are handled
                    # Stack tables
                    if len(all_coll) == 0:
                        all_coll = summary
                    else:
                        all_coll = vstack([all_coll, summary], metadata_conflicts='silent')

                else:
                    print(f"Warning: No FITS files found in {directory}")

            # Check final count of combined FITS files
            print(f"Total FITS files combined: {len(all_coll)}")
            if return_only_light:
                all_coll = all_coll[all_coll['imagetyp'] == 'LIGHT']
            return all_coll
        key = self.config['APPSCHEDULER_SEARCHKEY']
        key = key.replace("$$TONIGHT$$", tonight_str + '*')
        all_info = load_collection(key)
        if return_only_set:
            if all_info is None:
                return []
            all_info_set = []
            all_info_by_config = all_info.group_by(key_for_set).groups
            for all_info_group in all_info_by_config:
                all_info_set.append(dict(exptime = all_info_group[0]['exptime'], binning = all_info_group[0]['xbinning'], gain = all_info_group[0]['gain']))
            return all_info_set
        return all_info
    
    def _set_obsnight(self):
        obsnight = NightSession(Time.now())
        self.obsnight = obsnight.obsnight_ltc
        self.obsnight_utc = obsnight.obsnight_utc
        self.tonight_str = '%.4d-%.2d-%.2d'%(self.obsnight.sunset_civil.datetime.year, self.obsnight.sunset_civil.datetime.month, self.obsnight.sunset_civil.datetime.day)
        
    def set_alert_sender(self, post_tonight_info : bool = True):
        """
        Set the slack_alert_sender and slack_message_ts
        """
        self.slack_alert_sender = SlackConnector(token_path = self.config['SLACK_TOKEN'], default_channel_id = self.config['SLACK_DEFAULT_CHANNEL'])
        id_tonight = uuid.uuid4().hex
        self.slack_message_ts = self.slack_alert_sender.get_message_ts(match_string = f'{self.config["SYSTEM_NAME"]} Observation on {self.tonight_str}')
        if not self.slack_message_ts:
            # message_today = f'`{self.config["SYSTEM_NAME"]} Observation on {self.tonight_str}` \n *Involving telescopes*: {", ".join(list(self.multitelescopes.devices.keys()))} \n *Observation log*: https://hhchoi1022.notion.site/Observation-log-5af68b0822324167af57468b0852666b \n *ID*: {id_tonight}'
            message_today = f'`{self.config["SYSTEM_NAME"]} Observation on {self.tonight_str}`' + \
                            '\n *Observation Start*: ' + self.obsnight.sunset_observation.strftime('%Y-%m-%d %H:%M:%S') +\
                            '\n *Observation End*: ' + self.obsnight.sunrise_observation.strftime('%Y-%m-%d %H:%M:%S') +\
                            '\n *Observation Time*: ' + str(round(float(self.obsnight.observable_hour), 1)) + ' hours'
            result = self.slack_alert_sender.post_message(message_today)
            self.slack_message_ts = result['ts']

            if post_tonight_info:
                # Obsnight information
                obsnight_info_str = "*Tonight information*\n" + "```" +str(self.obsnight).split('Attributes:\n')[1].split('time_inputted')[0] + "```"
                self.post_slack_thread(message = obsnight_info_str, alert_slack = True)
                time.sleep(3)

    def post_schedule(self, subject : str = '*Scheduled TCSpy applications*'):
        if self.schedule.jobs:
            schedule_str = subject + '\n'
            contents = '' 
            for job in self.schedule.jobs:
                next_run = job.next_run.strftime("%Y-%m-%d %H:%M:%S")
                job_str = str(job)
                func_match = re.search(r"do=(\w+)", job_str)
                function_name = func_match.group(1) if func_match else "Unknown"
                # Extract kwargs using regex
                kwargs_match = re.search(r"kwargs=({.*?})", job_str)
                kwargs = kwargs_match.group(1) if kwargs_match else "{}"
                contents += f"{function_name}: {next_run} \nKwargs: {kwargs}\n\n"
            contents = f"```{contents}```"
            self.post_slack_thread(message = schedule_str+contents, alert_slack = True)
    
    def post_slack_thread(self, message, alert_slack: bool = True):
        if alert_slack:
            if not self.slack_alert_sender:
                self.set_alert_sender()
            self.slack_alert_sender.post_thread_message(message_ts = self.slack_message_ts, text = message)
        else:
            return 

    def _find_tonight_images(self, imgtype: str = None):
        """Return sorted list of FITS paths from tonight's image folder, optionally filtered by image type."""
        if self.multitelescopes.devices:
            tel_config = next(iter(self.multitelescopes.devices.values())).config
            image_path = tel_config.get('IMAGE_PATH', '/home/snu/code/RASA36/image/')
        else:
            image_path = '/home/snu/code/RASA36/image/'
        # Mirror the UTCDATE12- formula used in mainimage._format_foldername.
        # Sunset and sunrise can fall on different UTCDATE12- days (e.g. Chile near UTC noon),
        # so search folders matching either boundary date.
        import astropy.units as u
        sunset_date = (self.obsnight.sunset_civil - 12 * u.hour).datetime.strftime('%Y-%m-%d')
        sunrise_date = (self.obsnight.sunrise_shutdown - 12 * u.hour).datetime.strftime('%Y-%m-%d')
        dates = list(dict.fromkeys([sunset_date, sunrise_date]))
        raw_files = []
        for date in dates:
            pattern = os.path.join(image_path, f'*{date}*', '*.fits')
            raw_files.extend(glob.glob(pattern))
        files = sorted(set(raw_files))
        if imgtype:
            cal_types = ('_BIAS_', '_FLAT_', '_DARK_')
            if imgtype.upper() in ('BIAS', 'FLAT', 'DARK'):
                tag = f'_{imgtype.upper()}_'
                files = [f for f in files if tag in os.path.basename(f)]
            elif imgtype.upper() == 'LIGHT':
                files = [f for f in files if not any(t in os.path.basename(f) for t in cal_types)]
        return files

    def _fits_to_png(self, fits_path: str) -> str:
        """Convert a FITS file to PNG using ZScale normalization. Returns the PNG path."""
        from astropy.io import fits as astrofits
        from astropy.visualization import ZScaleInterval, ImageNormalize, LinearStretch
        import matplotlib.pyplot as plt
        png_path = fits_path.replace('.fits', '.png')
        with astrofits.open(fits_path) as hdul:
            data = hdul[0].data.astype(float)
        norm = ImageNormalize(data, interval=ZScaleInterval(), stretch=LinearStretch())
        fig, ax = plt.subplots(figsize=(8, 8), dpi=100)
        ax.imshow(data, cmap='gray', norm=norm, origin='lower', interpolation='none')
        ax.axis('off')
        plt.tight_layout(pad=0)
        plt.savefig(png_path, bbox_inches='tight')
        plt.close(fig)
        return png_path

    def _post_sample_image(self, imgtype: str, title_prefix: str, alert_slack: bool, first_and_last: bool = False):
        """Convert a representative FITS image to PNG and upload to the Slack thread."""
        if not alert_slack or not self.slack_alert_sender or not self.slack_message_ts:
            return
        files = self._find_tonight_images(imgtype=imgtype)
        if not files:
            self.multitelescopes.log.warning(f'[{type(self).__name__}] No {imgtype} images found to upload.')
            self.post_slack_thread(message=f'No {imgtype} images found to upload.', alert_slack=alert_slack)
            return
        self.multitelescopes.log.info(f'[{type(self).__name__}] Found {len(files)} {imgtype} image(s) to upload.')
        targets = [(files[0], 'First'), (files[-1], 'Last')] if (first_and_last and len(files) >= 2) else [(files[-1], '')]
        for fits_path, label in targets:
            try:
                png_path = self._fits_to_png(fits_path)
                title = f'{title_prefix} {label}: {os.path.basename(fits_path)}'.strip()
                self.slack_alert_sender.upload_file_to_thread(png_path, self.slack_message_ts, title=title)
                self.multitelescopes.log.info(f'[{type(self).__name__}] Uploaded {imgtype} sample: {os.path.basename(fits_path)}')
                os.remove(png_path)
            except Exception as e:
                self.multitelescopes.log.warning(f'[{type(self).__name__}] Failed to upload {imgtype} image to Slack: {e}', exc_info=True)

    @staticmethod
    def _complete_tile_names(tos_data, tonight_objnames: set) -> set:
        """Names of all tiles ever completed: TOS rows with obs_count > 0, unioned with
        tonight's observed tiles (which may not be flushed into obs_count yet). Names are
        normalized to str so they compare consistently with tile ids and Dynamic objnames."""
        ever = set(str(n) for n in tos_data['objname'][tos_data['obs_count'] > 0])
        return ever | set(str(n) for n in tonight_objnames)

    def _generate_sky_coverage_plot(self, db_tos, tonight_date: str, save_path: str, tonight_objnames: set) -> str:
        """Create a Mollweide sky coverage plot and save to save_path (never calls plt.show)."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon, Patch
        from astropy.io import ascii as astroascii

        tel_name = self.config.get('TEL_NAME', 'RASA36')
        tileinfo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'utils', 'databases', 'tileinfo', tel_name, 'final_tiles.txt'
        )
        tileinfo = astroascii.read(tileinfo_path)

        tos_data = db_tos.data
        tonight_names  = set(str(n) for n in tonight_objnames)
        complete_names = self._complete_tile_names(tos_data, tonight_names)
        ever_names     = complete_names - tonight_names  # previously observed only

        # Tiles that can never be selected under the survey cuts in
        # DB_Annual.select_best_targets — read from the same TARGET_* config
        # keys so this stays in sync automatically.
        from astropy.coordinates import SkyCoord
        gal_lat_limit = self.config.get('TARGET_GALACTIC_LATITUDE_LIMIT', 0)
        dec_upper_limit = self.config.get('TARGET_DECLINATION_UPPER_LIMIT', 20)
        dec_lower_limit = self.config.get('TARGET_DECLINATION_LOWER_LIMIT', -90)
        tile_coords = SkyCoord(tileinfo['ra'], tileinfo['dec'], unit='deg', frame='icrs')
        excluded_mask = ~((np.abs(tile_coords.galactic.b.value) > gal_lat_limit)
                        & (tile_coords.dec.value < dec_upper_limit)
                        & (tile_coords.dec.value > dec_lower_limit))
        excluded_names = set(str(n) for n in tileinfo['id'][excluded_mask]) - complete_names

        def to_rad(ra, dec):
            return np.deg2rad(ra - 180), np.deg2rad(dec)

        fig = plt.figure(figsize=(14, 7), dpi=150)
        ax = fig.add_subplot(111, projection='mollweide')

        for tile in tileinfo:
            name = str(tile['id'])
            corners = [(tile['ra1'], tile['dec1']), (tile['ra2'], tile['dec2']),
                       (tile['ra3'], tile['dec3']), (tile['ra4'], tile['dec4'])]
            corners_rad = [to_rad(r, d) for r, d in corners]
            if name in tonight_names:
                fc, ec, alpha = 'royalblue', 'royalblue', 0.7
            elif name in ever_names:
                fc, ec, alpha = 'tomato', 'tomato', 0.5
            elif name in excluded_names:
                fc, ec, alpha = 'darkgray', 'gray', 0.35
            else:
                fc, ec, alpha = 'none', 'gray', 0.25
            ax.add_patch(MplPolygon(corners_rad, closed=True,
                                    facecolor=fc, edgecolor=ec,
                                    alpha=alpha, linewidth=0.4))

        n_tonight    = len(tonight_names)
        n_ever       = len(complete_names)
        n_total      = len(tileinfo)
        n_excluded   = len(excluded_names)
        n_selectable = n_total - n_excluded
        n_pending    = n_selectable - n_ever
        pct     = 100 * n_ever / n_total if n_total else 0
        pct_sel = 100 * n_ever / n_selectable if n_selectable else 0

        ax.grid(True, linestyle='--', alpha=0.4)
        ax.set_xticklabels(
            ['14h', '16h', '18h', '20h', '22h', '0h', '2h', '4h', '6h', '8h', '10h'], fontsize=8)
        ax.set_title(
            f'TOS Sky Coverage  |  {tonight_date}\n'
            f'Tonight: {n_tonight} tiles   |   Selectable: {n_ever}/{n_selectable} ({pct_sel:.1f}%)'
            f'   |   Total: {n_ever}/{n_total} ({pct:.1f}%)',
            fontsize=11)
        ax.legend(handles=[
            Patch(facecolor='royalblue', label=f'Tonight ({n_tonight})'),
            Patch(facecolor='tomato',    label=f'Previously ({n_ever - n_tonight})'),
            Patch(facecolor='none', edgecolor='gray', label=f'Not observed ({n_pending})'),
            Patch(facecolor='darkgray', alpha=0.5,
                  label=f'Excluded by cuts ({n_excluded})'),
        ], loc='lower right', fontsize=8)

        plt.tight_layout()
        plt.savefig(save_path, bbox_inches='tight')
        plt.close(fig)
        return save_path

    def _post_night_summary(self, alert_slack: bool = True):
        """Post end-of-night Slack summary: image count, observed targets, TOS progress, ToO list."""
        if not alert_slack or not self.slack_alert_sender or not self.slack_message_ts:
            return
        try:
            tonight_date = self.tonight_str

            n_images = len(self._find_tonight_images('LIGHT'))

            db = DB()
            dyn_data = db.Dynamic.data
            observed  = dyn_data[dyn_data['status'] == 'observed']
            n_targets = len(observed)
            tonight_objnames = set(str(r) for r in observed['objname'])

            too_obs = observed[(observed['is_rapidToO'] == 1) | (observed['is_ToO'] == 1)]

            lines = [
                f':moon: *Night Observation Summary*  |  {tonight_date}',
                f'*Images taken:* {n_images} LIGHT frames',
                f'*Targets observed:* {n_targets}',
            ]

            if len(too_obs) > 0:
                too_names = ', '.join(str(r) for r in too_obs['objname'])
                lines += [
                    '',
                    f':rotating_light: *ToO Targets observed:* {len(too_obs)}',
                    f'  • {too_names}',
                ]

            tos_data = db.TOS.data
            n_complete = len(self._complete_tile_names(tos_data, tonight_objnames))
            n_total    = len(tos_data)
            pct = 100 * n_complete / n_total if n_total else 0
            if n_targets > 0 or n_complete > 0:
                lines += [
                    '',
                    ':bar_chart: *TOS Tile Survey Progress*',
                    f'  • Tiles observed tonight: {n_targets}',
                    f'  • Total complete tiles: {n_complete} / {n_total} ({pct:.1f}%)',
                ]

            self.post_slack_thread(message='\n'.join(lines), alert_slack=alert_slack)

            if n_targets > 0:
                plot_path = f'/tmp/sky_coverage_{tonight_date}.png'
                try:
                    self._generate_sky_coverage_plot(db.TOS, tonight_date, plot_path, tonight_objnames=tonight_objnames)
                    self.slack_alert_sender.upload_file_to_thread(
                        file_path=plot_path,
                        thread_ts=self.slack_message_ts,
                        title=f'TOS Sky Coverage ({tonight_date})',
                    )
                except Exception as e:
                    self.multitelescopes.log.warning(
                        f'[{type(self).__name__}] Sky coverage plot failed: {e}')
                finally:
                    if os.path.exists(plot_path):
                        os.remove(plot_path)

        except Exception as e:
            self.multitelescopes.log.error(
                f'[{type(self).__name__}] Night summary failed: {e}', exc_info=True)

    def run_filtercheck(self,
                        exptime = 60,
                        alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] FilterCheck started: {start_time}')
            self.post_slack_thread(message = f'Filtercheck is triggered: {start_time}', alert_slack = alert_slack)
            try:
                action = FilterCheck(self.multitelescopes, abort_action = self.abort_action)
                result = action.run(exptime = exptime)
                while action.is_running:
                    time.sleep(1)
                end_time = time.strftime("%H:%M:%S", time.localtime())
                self.multitelescopes.log.info(f'[{type(self).__name__}] FilterCheck finished: {end_time}')
                self.post_slack_thread(message = f'Filtercheck is finished: {end_time}', alert_slack = alert_slack)
                skylevel_str = '\n'.join([f'{band}: ' + ', '.join([f'{telescope}: {value} \n' for telescope, value in telescopes.items()])
                                        for band, telescopes in result[0].items()])
                self.multitelescopes.log.info(f'[{type(self).__name__}] Skylevel: {skylevel_str}')
                self.post_slack_thread(message=f'Skylevel:\n{skylevel_str}', alert_slack=alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] FilterCheck failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'FilterCheck failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob
 
    def run_db_dynamic(self,
                       alert_slack : bool = True,
                       clear_only_tos: bool = False,
                       clear_only_observed: bool = False):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] DB_Dynamic update started: {start_time}')
            self.post_slack_thread(message = f'DB_Dynamic update is triggered: {start_time}', alert_slack = alert_slack)
            db = None
            try:
                db = DB_Dynamic(Time.now())
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] DB_Dynamic connection failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'DB_Dynamic connection failed: {e}', alert_slack=alert_slack)
                return self.schedule.CancelJob
            try:
                self.multitelescopes.log.info(f'[{type(self).__name__}] Updating TOS obs count')
                db.update_TOS_obscount(remove=False, reset_status=False)
                self._post_night_summary(alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] TOS obs count update failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'TOS obs count update failed: {e}', alert_slack=alert_slack)
            try:
                self.multitelescopes.log.info(f'[{type(self).__name__}] Clearing DB_Dynamic')
                db.clear(clear_only_tos=clear_only_tos, clear_only_observed=clear_only_observed)
                self.multitelescopes.log.info(f'[{type(self).__name__}] Populating DB_Dynamic from TOS')
                db.from_TOS()
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] DB_Dynamic rebuild failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'DB_Dynamic rebuild failed: {e}', alert_slack=alert_slack)
            finally:
                db.disconnect()
            end_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] DB_Dynamic update finished: {end_time}')
            self.post_slack_thread(message=f'DB_Dynamic update is finished: {end_time}', alert_slack=alert_slack)
            return self.schedule.CancelJob

    def run_data_transfer(self,
                          alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] Data transfer started: {start_time}')
            self.post_slack_thread(message = f'Data transfer is triggered: {start_time}', alert_slack = alert_slack)
            dtm = DataTransferManager()
            images = self._find_tonight_images()
            matching_folders = sorted(set(os.path.dirname(f) for f in images))
            if matching_folders:
                self.multitelescopes.log.info(f'[{type(self).__name__}] Found {len(matching_folders)} folder(s) to transfer')
                for folder in matching_folders:
                    rel_key = os.path.relpath(folder, dtm.source_homedir)
                    self.multitelescopes.log.info(f'[{type(self).__name__}] Transferring: {rel_key}')
                    try:
                        dtm.run(key = rel_key,
                                save_hash = False,
                                tar = True,
                                transfer = True,
                                move_and_clean = True,
                                from_archive = False)
                        self.multitelescopes.log.info(f'[{type(self).__name__}] Transfer complete: {rel_key}')
                        self.post_slack_thread(message = f'Transfer complete: {rel_key}', alert_slack = alert_slack)
                    except Exception as e:
                        self.multitelescopes.log.error(f'[{type(self).__name__}] Transfer failed for {rel_key}: {e}', exc_info=True)
                        self.post_slack_thread(message = f'Transfer failed for {rel_key}: {e}', alert_slack = alert_slack)
            else:
                self.multitelescopes.log.warning(f'[{type(self).__name__}] No tonight images found to transfer')
                self.post_slack_thread(message = f'No tonight images found to transfer', alert_slack = alert_slack)
            end_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] Data transfer finished: {end_time}')
            self.post_slack_thread(message = f'Data transfer is finished: {end_time}', alert_slack = alert_slack)
            return self.schedule.CancelJob

    def run_startup(self,
                    home = True,
                    slew = True,
                    cool = True,
                    alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] Startup started: {start_time}')
            self.post_slack_thread(message = f'StartUp is triggered: {start_time}', alert_slack = alert_slack)
            try:
                action = Startup(self.multitelescopes, abort_action = self.abort_action)
                action.run(home = home, slew = slew, cool = cool)
                while action.is_running:
                    time.sleep(1)
                end_time = time.strftime("%H:%M:%S", time.localtime())
                if action.succeeded:
                    self.multitelescopes.log.info(f'[{type(self).__name__}] Startup finished: {end_time}')
                    self.post_slack_thread(message = f'StartUp is finished: {end_time}', alert_slack = alert_slack)
                else:
                    reason_str = f' ({action.failure_reason.rstrip("; ")})' if action.failure_reason else ''
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] Startup failed: {end_time}')
                    self.post_slack_thread(message = f'StartUp failed{reason_str}: {end_time}', alert_slack = alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] Startup failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'Startup failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob
 
    def run_nightobs(self,
                     alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] NightObservation started: {start_time}')
            self.post_slack_thread(message = f'NightObservation is triggered: {start_time}', alert_slack = alert_slack)
            try:
                action = NightObservation(
                    self.multitelescopes,
                    abort_action = self.abort_action,
                    slack = self.slack_alert_sender if alert_slack else None,
                    message_ts = self.slack_message_ts,
                )
                action.run()
                while action.is_running:
                    time.sleep(1)
                end_time = time.strftime("%H:%M:%S", time.localtime())
                self.multitelescopes.log.info(f'[{type(self).__name__}] NightObservation finished: {end_time}')
                self.post_slack_thread(message = f'NightObservation is finished: {end_time}', alert_slack = alert_slack)
                DB().Dynamic.export_to_csv(save_type= 'history')
                self._post_sample_image('LIGHT', 'Night Obs Light', alert_slack, first_and_last=True)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] NightObservation failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'NightObservation failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob

    def run_bias(self,
                 count : int = 10,
                 binning : int = 1,
                 gain : int = 16,
                 alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] BiasAcquisition started: {start_time} (count={count}, binning={binning}, gain={gain})')
            self.post_slack_thread(message = f'BiasAcquisition is triggered: {start_time}', alert_slack = alert_slack)
            try:
                action = BiasAcquisition(self.multitelescopes, abort_action = self.abort_action)
                action.run(count = count, binning = binning, gain = gain)
                while action.is_running:
                    time.sleep(1)
                end_time = time.strftime("%H:%M:%S", time.localtime())
                if action.succeeded:
                    self.multitelescopes.log.info(f'[{type(self).__name__}] BiasAcquisition finished: {end_time}')
                    self.post_slack_thread(message = f'BiasAcquisition is finished: {end_time}', alert_slack = alert_slack)
                    self._post_sample_image('BIAS', 'BIAS sample', alert_slack)
                else:
                    reason_str = f' ({action.failure_reason.rstrip("; ")})' if action.failure_reason else ''
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] BiasAcquisition failed: {end_time}')
                    self.post_slack_thread(message = f'BiasAcquisition failed{reason_str}: {end_time}', alert_slack = alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] BiasAcquisition failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'BiasAcquisition failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob
    
    def run_dark(self,
                 count : int = 10,
                 exptime : float = 60,
                 binning : int = 1,
                 gain : int = 16,
                 obsinfo_list : list = None,
                 alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            if obsinfo_list is None:
                obsinfo_list = [dict(exptime=exptime, binning=binning, gain=gain)]
            configs_str = ', '.join(f'{float(o["exptime"]):.1f}s' for o in obsinfo_list)
            self.multitelescopes.log.info(f'[{type(self).__name__}] DarkAcquisition started: {start_time} (count={count}, configs=[{configs_str}])')
            self.post_slack_thread(message = f'DarkAcquisition is triggered: {start_time}', alert_slack = alert_slack)
            all_succeeded = True
            dark_failure_reasons = []
            try:
                for obsinfo in obsinfo_list:
                    exp  = float(obsinfo['exptime'])
                    bin_ = int(obsinfo['binning'])
                    gn   = int(obsinfo['gain'])
                    self.multitelescopes.log.info(f'[{type(self).__name__}] Dark batch: exptime={exp}s, binning={bin_}, gain={gn}')
                    action = DarkAcquisition(self.multitelescopes, abort_action = self.abort_action)
                    action.run(count = count, exptime = exp, binning = bin_, gain = gn)
                    time.sleep(0.5)
                    while action.is_running:
                        time.sleep(1)
                    if action.succeeded:
                        self._post_sample_image('DARK', f'DARK sample ({exp:.1f}s)', alert_slack)
                    else:
                        all_succeeded = False
                        dark_failure_reasons.append(f'{exp:.1f}s: {action.failure_reason.rstrip("; ")}' if action.failure_reason else f'{exp:.1f}s: unknown')
                        self.multitelescopes.log.warning(f'[{type(self).__name__}] Dark batch failed: exptime={exp}s')
                end_time = time.strftime("%H:%M:%S", time.localtime())
                if all_succeeded:
                    self.multitelescopes.log.info(f'[{type(self).__name__}] DarkAcquisition finished: {end_time}')
                    self.post_slack_thread(message = f'DarkAcquisition is finished: {end_time}', alert_slack = alert_slack)
                else:
                    reason_str = f' ({"; ".join(dark_failure_reasons)})' if dark_failure_reasons else ''
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] DarkAcquisition failed: {end_time}')
                    self.post_slack_thread(message = f'DarkAcquisition failed{reason_str}: {end_time}', alert_slack = alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] DarkAcquisition failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'DarkAcquisition failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob

    def run_flat(self,
                 count : int = 10,
                 binning : int = 1,
                 gain : int = 16,
                 alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] FlatAcquisition started: {start_time} (count={count}, binning={binning}, gain={gain})')
            self.post_slack_thread(message = f'FlatAcquisition is triggered: {start_time}', alert_slack = alert_slack)
            try:
                action = FlatAcquisition(self.multitelescopes, abort_action = self.abort_action)
                action.run(count = count, binning = binning, gain = gain)
                while action.is_running:
                    time.sleep(1)
                end_time = time.strftime("%H:%M:%S", time.localtime())
                if action.succeeded:
                    self.multitelescopes.log.info(f'[{type(self).__name__}] FlatAcquisition finished: {end_time}')
                    self.post_slack_thread(message = f'FlatAcquisition is finished: {end_time}', alert_slack = alert_slack)
                    self._post_sample_image('FLAT', 'FLAT sample', alert_slack)
                else:
                    reason_str = f' ({action.failure_reason.rstrip("; ")})' if action.failure_reason else ''
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] FlatAcquisition failed: {end_time}')
                    self.post_slack_thread(message = f'FlatAcquisition failed{reason_str}: {end_time}', alert_slack = alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] FlatAcquisition failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'FlatAcquisition failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob

    def run_shutdown(self,
                     fanoff : bool = True,
                     slew : bool = True,
                     warm : bool = True,
                     alert_slack : bool = True):
        with self.thread_lock:
            start_time = time.strftime("%H:%M:%S", time.localtime())
            self.multitelescopes.log.info(f'[{type(self).__name__}] Shutdown started: {start_time}')
            self.post_slack_thread(message = f'Shutdown is triggered: {start_time}', alert_slack = alert_slack)
            try:
                action = Shutdown(self.multitelescopes, abort_action = self.abort_action)
                action.run(fanoff = fanoff, slew = slew, warm = warm)
                while action.is_running:
                    time.sleep(1)
                end_time = time.strftime("%H:%M:%S", time.localtime())
                if action.succeeded:
                    self.multitelescopes.log.info(f'[{type(self).__name__}] Shutdown finished: {end_time}')
                    self.post_slack_thread(message = f'Shutdown is finished: {end_time}', alert_slack = alert_slack)
                else:
                    reason_str = f' ({action.failure_reason.rstrip("; ")})' if action.failure_reason else ''
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] Shutdown failed: {end_time}')
                    self.post_slack_thread(message = f'Shutdown failed{reason_str}: {end_time}', alert_slack = alert_slack)
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] Shutdown failed: {e}', exc_info=True)
                self.post_slack_thread(message=f'Shutdown failed: {e}', alert_slack=alert_slack)
            return self.schedule.CancelJob
  
    def show_schedule(self,
                      alert_slack : bool = True):
        if not self.schedule.jobs:
            print("No scheduled jobs.")
            return

        print("Current Schedule:")
        for job in self.schedule.jobs:
            next_run = job.next_run.strftime("%Y-%m-%d %H:%M:%S")
            job_str = str(job)
            func_match = re.search(r"do=(\w+)", job_str)
            function_name = func_match.group(1) if func_match else "Unknown"
            # Extract kwargs using regex
            kwargs_match = re.search(r"kwargs=({.*?})", job_str)
            kwargs = kwargs_match.group(1) if kwargs_match else "{}"
            print(f"{function_name} | Next run: {next_run} | Job: {function_name} | kwargs: {kwargs}")

    def clear_schedule(self):
        self.schedule.clear()
             
    def schedule_app(self, application, start_time : Time, **application_kwargs):
        start_time_str = '%.2d:%.2d:%.2d'%(start_time.datetime.hour, start_time.datetime.minute, start_time.datetime.second)
        self.schedule.every().day.at(start_time_str).do(application, **application_kwargs)

    def run_schedule(self):
        while self.schedule.get_jobs():
            try:
                self.schedule.run_pending()
            except Exception as e:
                self.multitelescopes.log.error(f'[{type(self).__name__}] Scheduler error: {e}', exc_info=True)
            time.sleep(1)
            
    def dummy_run(self):
        print('Dummy run')
        return self.schedule.CancelJob
            

# %%
if __name__ == '__main__':
    M = MultiTelescopes()
    abort_action = Event()
    A = AppScheduler(M, abort_action)

    _original_sigint = signal.getsignal(signal.SIGINT)
    def _sigint_handler(signum, frame):
        abort_action.set()
        signal.signal(signal.SIGINT, _original_sigint)  # restore: second Ctrl+C force-kills
    signal.signal(signal.SIGINT, _sigint_handler)
    signal.signal(signal.SIGTERM, _sigint_handler)
    A.clear_schedule()
    alert_slack = True
    # Filtercheck
    # if Time.now() < A.obsnight_utc.sunset_flat:
    #     A.schedule_app(A.run_filtercheck, A.obsnight.sunset_flat, exptime = 60)
    
    # # Startup
    if Time.now() < A.obsnight_utc.sunset_startup:
        A.schedule_app(A.run_startup, A.obsnight.sunset_startup, home = True, slew = True, cool = True, alert_slack = alert_slack)
    
    # NightObservation
    if Time.now() < A.obsnight_utc.sunset_observation:
        A.schedule_app(A.run_nightobs, A.obsnight.sunset_observation, alert_slack = alert_slack)

    A.set_alert_sender(post_tonight_info= True)
    A.post_schedule(subject = '*Scheduled TCSpy apploication before nightly observation*')
    A.show_schedule()

    if A.schedule.jobs:
        A.run_schedule()
        time.sleep(10)
        A.clear_schedule()

    while Time.now() < A.obsnight_utc.sunrise_observation + 5 * u.minute:
        time.sleep(1)

    # DB_Dynamic: update TOS, post night summary, then repopulate for next night
    A.run_db_dynamic(alert_slack=alert_slack, clear_only_tos=False, clear_only_observed=False)

    # Flat
    flat_count = 10
    all_obsinfo = A.get_obsinfo_tonight(A.tonight_str, return_only_set= True, key_for_set = ['xbinning', 'gain'])
    if Time.now() < A.obsnight_utc.sunrise_flat:
        for obsinfo in all_obsinfo:
            A.schedule_app(A.run_flat, A.obsnight.sunrise_flat, count = int(flat_count), binning = int(obsinfo['binning']), gain = int(obsinfo['gain']), alert_slack = alert_slack)

    # Dark
    all_obsinfo = A.get_obsinfo_tonight(A.tonight_str, return_only_set= True, key_for_set = ['exptime', 'xbinning', 'gain'])
    dark_count = 10
    dark_starttime = A.obsnight.sunrise_flat + 15 * u.minute
    dark_starttime_utc = A.obsnight_utc.sunrise_flat + 15 * u.minute
    if Time.now() < dark_starttime_utc and all_obsinfo:
        A.schedule_app(A.run_dark, dark_starttime, count = int(dark_count), obsinfo_list = all_obsinfo, alert_slack = alert_slack)
        total_dark_duration = sum(float(o['exptime']) * dark_count * 1.3 for o in all_obsinfo)
        dark_starttime += total_dark_duration * u.second
        dark_starttime_utc += total_dark_duration * u.second

    # Bias
    all_obsinfo = A.get_obsinfo_tonight(A.tonight_str, return_only_set= True, key_for_set= ['xbinning', 'gain'])
    bias_count = 10
    bias_starttime = dark_starttime + 10 * u.minute
    bias_starttime_utc = dark_starttime_utc + 10 * u.minute
    if Time.now() < bias_starttime_utc:
        for obsinfo in all_obsinfo:
            A.schedule_app(A.run_bias, bias_starttime, count = int(bias_count), binning = int(obsinfo['binning']), gain = int(obsinfo['gain']), alert_slack = alert_slack)
            bias_starttime += 10 * u.minute
            bias_starttime_utc += 10 * u.minute

    # Shutdown
    shutdown_starttime = A.obsnight_utc.sunrise_shutdown
    if Time.now() < shutdown_starttime:
        A.schedule_app(A.run_shutdown, A.obsnight.sunrise_shutdown, fanoff = True, slew = True, warm = True, alert_slack = alert_slack)

    # Data transfer
    A.schedule_app(A.run_data_transfer, A.obsnight.sunrise_shutdown + 3 * u.minute, alert_slack = alert_slack)

    A.post_schedule(subject = '*Scheduled TCSpy application after nightly observation*')
    A.show_schedule()
    A.run_schedule()
    abort_action.set()

# %%
