#%%
import time
import os
import subprocess
import glob
import hashlib
import json
import portalocker
from tqdm import tqdm
from astropy.time import Time
from typing import Optional
from datetime import datetime
from collections import defaultdict
from tcspy.configuration import mainConfig
#%%
class DataTransferManager(mainConfig):

    def __init__(self):
        super().__init__()
        self.source_homedir = self.config['TRANSFER_SOURCE_HOMEDIR']
        self.archive_homedir = self.config['TRANSFER_ARCHIVE_HOMEDIR']
        self.server_homedir = self.config['TRANSFER_SERVER_HOMEDIR']
        self.server = self._set_server(**self.config)
        # self.gridftp = self._set_gridftp_params(**self.config)
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.too_last_seen = None
        self.slack = None
        # Set externally (e.g., by AppScheduler) to post regular transfer notifications as thread replies
        self.slack_thread_ts = None

    def _set_slack(self):
        if not self.slack:
            from tcspy.utils.connector import SlackConnector
            self.slack = SlackConnector(
                token_path=self.config['SLACK_TOKEN'],
                default_channel_id=self.config['SLACK_DEFAULT_CHANNEL']
            )

    def _check_observation_finished(self, recent_threshold_seconds=60):
        """Check if observation just finished by reading the statusfile.

        Returns True if all telescopes are 'idle' and status was updated recently,
        indicating that an observation sequence just completed.

        Args:
            recent_threshold_seconds: How recent the status update must be (default 60s)
        """
        try:
            status_file = self.config.get('MULTITELESCOPES_FILE')
            if not status_file or not os.path.exists(status_file):
                return False

            with portalocker.Lock(status_file, 'r', timeout=2) as f:
                status_dict = json.load(f)

            # Check if any telescope status was recently updated to idle
            current_time = Time.now()
            for tel_name, tel_status in status_dict.items():
                if not isinstance(tel_status, dict):
                    continue

                status = tel_status.get('Status', '').lower()
                status_update_time_str = tel_status.get('Status_update_time')

                if status != 'idle' or not status_update_time_str:
                    continue

                # Check if status was updated recently
                try:
                    status_update_time = Time(status_update_time_str, format='isot')
                    time_since_update = (current_time - status_update_time).sec

                    if 0 <= time_since_update <= recent_threshold_seconds:
                        return True
                except Exception:
                    continue

            return False

        except Exception as e:
            # Don't break transfer on statusfile read errors - just log and continue
            print(f"Warning: Could not read statusfile for observation check: {e}")
            return False

    def start_monitoring(self, ordinary_file_key = '*/image/*', ToO_file_key = '*/image/*_ToO', inactivity_period = 1800, poll_interval = 60, save_hash = True, tar = True, transfer = True, move_and_clean = True, protocol = 'hpnscp'):
        """Monitor files and initiate transfers."""
        print(f'Monitoring started since {Time.now().isot}')
        while True:
            try:
                current_time = datetime.now()
                # if current_time.hour == 12 and current_time.minute == 0:
                #     self.transfer_ordinary_files(ordinary_file_key = ordinary_file_key, tar = tar, protocol = protocol)
                self.transfer_ToO_files(inactivity_period = inactivity_period, ToO_file_key = ToO_file_key, save_hash= save_hash, tar = tar, transfer = transfer, move_and_clean = move_and_clean, protocol = protocol)
            except Exception as e:
                print(f"Monitoring loop error: {e}")

            time.sleep(poll_interval)

    def transfer_ordinary_files(self, ordinary_file_key = '*/image/*', save_hash = True, tar = True, sync_log = True, transfer = True, move_and_clean = True, protocol = 'hpnscp'):
        """Transfer ordinary files at 8 AM."""
        print(f"Ordinary file transfer triggered at {Time.now().isot}")
        folder_list = set([os.path.basename(folder) for folder in (glob.glob(os.path.join(self.source_homedir, ordinary_file_key)))])
        if len(folder_list) > 0:
            print(f"Transferring ordinary files at {Time.now().isot}")
            for folder in folder_list:
                key = os.path.join(os.path.dirname(ordinary_file_key), folder)
                print('Transferring folder:', key)
                try:
                    self.run(key = key, save_hash = save_hash, tar = tar, sync_log = sync_log, transfer = True, move_and_clean = True, protocol = protocol)
                    print(f"Transfer complete: {key}")
                except Exception as e:
                    print(f"Transfer failed for {key}: {e}")
        
    def transfer_ToO_files(self, inactivity_period, ToO_file_key = '*/image/*_ToO', save_hash = True, tar = True, transfer = True, move_and_clean = True, protocol = 'hpnscp'):
        """Transfer ToO files immediately when observation finishes, or after inactivity period as fallback."""
        all_files = glob.glob(os.path.join(self.source_homedir, ToO_file_key, '*'))
        # Skip files inside folders that have already been transferred
        too_files = [f for f in all_files if not os.path.exists(os.path.join(os.path.dirname(f), '.transferred'))]
        folder_list = set([os.path.basename(os.path.dirname(file_)) for file_ in too_files])
        if too_files:
            latest_file_time = max([os.path.getmtime(file_) for file_ in too_files])

            if self.too_last_seen is None or latest_file_time > self.too_last_seen:
                self.too_last_seen = latest_file_time

            # Check if observation just finished (via statusfile) for immediate transfer
            observation_finished = self._check_observation_finished(recent_threshold_seconds=60)

            # Also ensure files are at least a few seconds old to avoid race conditions
            files_settled = (time.time() - self.too_last_seen) >= 5

            should_transfer = False
            if observation_finished and files_settled:
                print(f"ToO observation finished (statusfile check) - triggering immediate transfer at {Time.now().isot}")
                should_transfer = True
            elif time.time() - self.too_last_seen >= inactivity_period:
                print(f"ToO inactivity period ({inactivity_period}s) elapsed - transferring at {Time.now().isot}")
                should_transfer = True
            else:
                inactivity_elapsed = time.time() - self.too_last_seen
                print(f"ToO files found. Waiting for observation finish or inactivity ({inactivity_elapsed:.0f}/{inactivity_period}s elapsed)...")

            if should_transfer:
                for folder in folder_list:
                    key = os.path.join(os.path.dirname(ToO_file_key), folder)
                    print(f"Transferring ToO folder: {key}")
                    try:
                        self.run(key=key, save_hash = save_hash, tar = tar, transfer = transfer, move_and_clean = move_and_clean, protocol = protocol, sync_log = True)
                        print(f"Transfer complete: {key}")
                    except Exception as e:
                        print(f"Transfer failed for {key}: {e}")
                    self.too_last_seen = None
        
    def run(self,
            key: str = '*/image/20240515',
            output_file_name: str = None,
            save_hash : bool = True,
            tar : bool = True,
            sync_log : bool = True,
            transfer : bool = True,
            move_and_clean : bool = True,
            protocol : str = 'hpnscp',
            from_archive : bool = False):
        source_dir = self.source_homedir
        if from_archive:
            self.source_homedir = self.archive_homedir
        try:
            if protocol == 'hpnscp':
                self.hpnscp_transfer(key = key, output_file_name= output_file_name, save_hash = save_hash, tar = tar, sync_log = sync_log, transfer = transfer, move_and_clean = move_and_clean)
            else:
                # self.gridFTP_transfer(...)
                pass
        finally:
            self.source_homedir = source_dir
        
    def abort(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)  # Wait for the process to terminate
                print("Transfer terminated successfully.")
            except subprocess.TimeoutExpired:
                self.process.kill()
                print("Transfer forcefully killed after timeout.")
            finally:
                self.process = None
        else:
            print("No running transfer to terminate.")
            
    # def gridFTP_transfer(self,
    #                      key : str = '*/image/20240515',
    #                      output_file_name : str =  None,
    #                      save_hash: bool = True,
    #                      tar : bool = True,
    #                      sync_log: bool = True,
    #                      transfer : bool = True,
    #                      move_and_clean : bool = True):
    #     self.is_running = True
    #     if save_hash:
    #         self.generate_and_save_hash(source_file_key=key)
    #     if not output_file_name:
    #         output_file_name = os.path.basename(key)+'.tar'
    #     verbose_command = ''
    #     if self.gridftp.verbose:
    #         verbose_command = '-vb'
    #     if tar:
    #         source_path = self.tar(source_file_key= key, output_file_key = f'{os.path.join(self.archive_homedir, output_file_name)}', compress = False, sync_log = sync_log)
    #     else:
    #         source_path = f'{os.path.join(self.archive_homedir, output_file_name)}'
    #     logfile = f'/data2/obsdata/transfer_history/{Time.now().isot}.log'
    #     command = f"globus-url-copy {verbose_command} -fast -dbg -p {self.gridftp.numparallel} -rst-retries {self.gridftp.numretries} -rst-interval {self.gridftp.retryinterval} file:{source_path} sshftp://{self.server.username}@{self.server.ip}:{self.server.portnum}{self.server_homedir} > {logfile}"
    #     #try:
    #     if transfer:
    #         print('GRIDFTP PROTOCOL WITH THE COMMAND:',command)
    #         self.process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #         stdout, stderr = self.process.communicate()
    #         if self.process.returncode == 0:
    #             print(f"Transfer successful: {stdout.decode()}")
    #         else:
    #             raise RuntimeError(f"Error during transfer: {stderr.decode()}")
    #     #except:
    #     #    self.process = None
    #     #    self.is_running = False

    #     if move_and_clean:
    #         self.move_to_archive_and_cleanup(key, source_path)
    #     self.process = None
    #     self.is_running = False

    def hpnscp_transfer(self,
                        key : str = '*/image/20240503',
                        output_file_name : str = None,
                        save_hash: bool = True,
                        tar : bool = True,
                        sync_log: bool = True,
                        transfer : bool = True,
                        move_and_clean : bool = True
                        ):
        self.is_running = True
        if save_hash:
            self.generate_and_save_hash(source_file_key=key)
        if not output_file_name:
            output_file_name = os.path.basename(key)+'.tar'
        if tar:
            source_path = self.tar(source_file_key= key, output_file_key = f'{os.path.join(self.archive_homedir, output_file_name)}', compress = False, sync_log = sync_log)
        else:
            source_path = f'{os.path.join(self.archive_homedir, output_file_name)}'
        command = f"hpnscp -P {self.server.portnum} {source_path} {self.server.username}@{self.server.ip}:{self.server_homedir}"
        max_retries = 5
        default_retry_delay = 3
        # kex_exchange_identification/"Connection reset by peer" on attempt 1 has recovered
        # cleanly on the very next attempt every time we've seen it (RASA36 2026-07-12/13) —
        # safe to retry that specific case fast. Other failures are less characterized, so
        # they keep the conservative default delay.
        reset_peer_retry_delay = 1
        next_retry_delay = default_retry_delay
        if transfer:
            print('HPNSSH PROTOCOL WITH THE COMMAND:',command)
            file_size = os.path.getsize(source_path)
            size_str = f"{file_size/1024**3:.2f} GB" if file_size >= 1024**3 else f"{file_size/1024**2:.1f} MB"
            transfer_start = time.time()
            for attempt in range(1, max_retries + 1):
                try:
                    if attempt > 1:
                        print(f"Retry {attempt}/{max_retries} in {next_retry_delay}s...")
                        time.sleep(next_retry_delay)
                    self.process = subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    with tqdm(total=None, desc=f'Transferring {size_str} (attempt {attempt}/{max_retries})',
                              bar_format='{desc} | elapsed: {elapsed}') as pbar:
                        while self.process.poll() is None:
                            time.sleep(1)
                            pbar.update(1)
                    if self.process.returncode == 0:
                        print(f"Transfer successful")
                        try:
                            sentinel_cmd = (
                                f"ssh -p {self.server.portnum} "
                                f"{self.server.username}@{self.server.ip} "
                                f"'touch {self.server_homedir}/{output_file_name}.done'"
                            )
                            subprocess.run(sentinel_cmd, shell=True, check=True,
                                           capture_output=True, timeout=30)
                            print(f"Sentinel created: {output_file_name}.done")
                        except Exception as e:
                            print(f"Warning: failed to create sentinel file on server: {e}")
                        try:
                            self._set_slack()
                            tar_size = os.path.getsize(source_path)
                            elapsed = time.time() - transfer_start
                            size_gb = tar_size / 1024**3
                            size_str = f"{size_gb:.2f} GB" if tar_size >= 1024**3 else f"{tar_size/1024**2:.1f} MB"
                            speed_mbs = (tar_size / 1024**2) / elapsed if elapsed > 0 else 0
                            speed_str = f"{speed_mbs/1024:.2f} GB/s" if speed_mbs >= 1024 else f"{speed_mbs:.1f} MB/s"
                            if elapsed >= 3600:
                                duration_str = f"{int(elapsed//3600)}h {int(elapsed%3600//60)}m {int(elapsed%60)}s"
                            elif elapsed >= 60:
                                duration_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"
                            else:
                                duration_str = f"{elapsed:.0f}s"
                            msg = (
                                f':white_check_mark: *Data transfer complete* — '
                                f'`{output_file_name}` ({size_str}) transferred to `{self.server.ip}` '
                                f'at {Time.now().isot}\n'
                                f'Duration: `{duration_str}` | Speed: `{speed_str}`'
                            )
                            # Determine target Slack thread: ToO alert thread > scheduler thread > channel message
                            thread_ts = None
                            folder_name = os.path.basename(key.rstrip('/'))
                            is_too = '_ToO' in key or '_too' in key or '_TOO' in key
                            if is_too:
                                statuspath = self.config.get('ALERTBROKER_STATUSPATH', '')
                                if statuspath and os.path.isdir(statuspath):
                                    statuses = []
                                    for sf in glob.glob(os.path.join(statuspath, '*', 'alert_status.json')):
                                        try:
                                            with open(sf) as f:
                                                statuses.append(json.load(f))
                                        except Exception:
                                            pass
                                    # Pass 1: match the short row-id suffix embedded in the folder
                                    # name (e.g. <date>_gain<g>_<target_name>_<id8>_ToO) against the
                                    # alert's own id. This is unambiguous even when two independent
                                    # dispatches share the same target name (e.g. a target re-alerted,
                                    # or an accidental duplicate trigger), unlike the name-only match.
                                    for status in statuses:
                                        ts = status.get('slack_ts')
                                        alert_key = str(status.get('key', '') or '')
                                        if ts and alert_key and f'_{alert_key[:8]}_ToO' in folder_name:
                                            thread_ts = ts
                                            break
                                    # Pass 2: fall back to target-name matching for folders written
                                    # before the id suffix existed, or dispatches with no id.
                                    if thread_ts is None:
                                        for status in statuses:
                                            ts = status.get('slack_ts')
                                            target_names = status.get('target_names', [])
                                            if ts and any(f'_{name}_ToO' in folder_name for name in target_names):
                                                thread_ts = ts
                                                break
                            if thread_ts is None:
                                thread_ts = self.slack_thread_ts
                            if thread_ts:
                                self.slack.post_thread_message(message_ts=thread_ts, text=msg)
                                print(f"Transfer notification posted to Slack thread: {thread_ts}")
                            else:
                                self.slack.post_message(text=msg)
                        except Exception as e:
                            print(f"Failed to post transfer notification to Slack: {e}")
                        break
                    stderr_output = self.process.stderr.read().decode()
                    raise RuntimeError(f"Return code {self.process.returncode}: {stderr_output.strip()}")
                except Exception as e:
                    print(f"Transfer error (attempt {attempt}/{max_retries}): {e}")
                    self.process = None
                    err_str = str(e)
                    if 'kex_exchange_identification' in err_str or 'Connection reset by peer' in err_str:
                        next_retry_delay = reset_peer_retry_delay
                    else:
                        next_retry_delay = default_retry_delay
                    if attempt == max_retries:
                        self.is_running = False
                        raise RuntimeError(f"Transfer failed after {max_retries} attempts: {e}") from e
        if move_and_clean:
            self.move_to_archive_and_cleanup(key, source_path)
        self.process = None
        self.is_running = False

    def generate_and_save_hash(self, source_file_key: str) -> None:
        """
        Generates SHA-256 hashes for all files matching the given pattern
        and saves each hash as a separate file in the same directory.

        Parameters:
        source_file_key (str): Glob pattern to match source files (e.g., '7DT/*.fits').

        Returns:
        None
        """
        try:
            # Match all files using the provided pattern
            source_keys = os.path.join(self.source_homedir, source_file_key, '*')
            file_paths = glob.glob(source_keys)
            if not file_paths:
                raise ValueError(f"No files matched the pattern: {source_file_key}")

            dir_path_dict = defaultdict(list)
            for path in file_paths:
                if os.path.isfile(path):
                    dir_path_dict[os.path.dirname(path)].append(path)

            for dir_path, dir_files in dir_path_dict.items():
                dir_name = os.path.basename(dir_path)
                hashlist = []
                filenamelist = []
                for file_path in tqdm(dir_files, desc=f'Generating hashes in {dir_name}...'):
                    hasher = hashlib.sha256()
                    with open(file_path, 'rb') as file:
                        for chunk in iter(lambda: file.read(4096), b""):
                            hasher.update(chunk)
                    hashlist.append(hasher.hexdigest())
                    filenamelist.append(os.path.basename(file_path))

                hash_file_path = os.path.join(dir_path, 'allfiles.hash')
                with open(hash_file_path, 'w') as hash_file:
                    for hash_, filename in zip(hashlist, filenamelist):
                        hash_file.write(f"{hash_} {filename}\n")
                print(f"Hash generated and saved: {hash_file_path}")

        except Exception as e:
            raise RuntimeError(f"An error occurred while generating and saving hashes: {str(e)}")

    def tar(self,
            source_file_key : str,
            output_file_key : str,
            compress : bool = False,
            sync_log: bool = True):
        compress_command = '-cv --blocking-factor=1024'
        if compress:
            compress_command = "-cv --blocking-factor=1024 --use-compress-program='zstd -T0'"
            output_file_key = output_file_key.replace('.tar', '.tar.zst')
        command = f'tar {compress_command} -f {output_file_key} -C {self.source_homedir} {source_file_key}'
        total_files = len(glob.glob(os.path.join(self.source_homedir, source_file_key, '*')))
        try:
            print(f"Tarball started: {Time.now().isot}")
            self.process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            with tqdm(total=total_files or None, desc='Archiving', unit='file') as pbar:
                for line in self.process.stdout:
                    pbar.update(1)
                    pbar.set_postfix({'file': os.path.basename(line.strip())[-40:]})
            self.process.wait()
            stderr_output = self.process.stderr.read()
            if self.process.returncode == 0:
                print(f"Tarball successful")
            else:
                raise RuntimeError(f"Tarball failed: {stderr_output.strip()}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Tarball failed: {e}") from e
        finally:
            self.process = None
            
        # Step 3: Log tar file name and size
        if sync_log:
            try:
                tar_full_path = os.path.abspath(output_file_key)
                tar_size = os.path.getsize(tar_full_path)
                log_file = self.config['TRANSFER_SYNC']
                with open(log_file, 'a') as f:
                    f.write(f"{os.path.basename(tar_full_path)}\t{tar_size} bytes\t {Time.now().isot}\n")
                print(f"Tar file info logged at: {log_file}")
            except Exception as e:
                print(f"Failed to log tar file info: {e}")
                
        return output_file_key
        
    def move_to_archive_and_cleanup(self, key, tar_path):

        # Remove the tar file
        try:
            os.remove(tar_path)
            print(f"Removed tar file: {tar_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to remove tar file {tar_path}: {e}") from e

        # Mark source folder as transferred so it is not picked up again on the next poll
        source_folder = os.path.join(self.source_homedir, key)
        if os.path.exists(source_folder):
            try:
                open(os.path.join(source_folder, '.transferred'), 'w').close()
                print(f"Marked as transferred: {source_folder}")
            except Exception as e:
                print(f"Warning: failed to mark {source_folder}: {e}")

    def _set_server(self,
                    TRANSFER_SERVER_IP,
                    TRANSFER_SERVER_USERNAME,
                    TRANSFER_SERVER_PORTNUM,
                    **kwrags
                    ):    
        class server: 
            ip = TRANSFER_SERVER_IP
            username = TRANSFER_SERVER_USERNAME
            portnum = TRANSFER_SERVER_PORTNUM
            def __repr__(self): 
                return ('SERVER CONFIGURATION ============\n'
                        f'server.ip = {self.ip}\n'
                        f'server.username = {self.username}\n'
                        f'server.portnum = {self.portnum}\n' 
                        '=================================')
        return server()
        
    # def _set_gridftp_params(self,
    #                         TRANSFER_GRIDFTP_NUMPARALLEL : int = 64, # Number of parallel data connection
    #                         TRANSFER_GRIPFTP_VERBOSE : bool = True, # Verbose?
    #                         TRANSFER_GRIDFTP_RETRIES : int = 10, # Number of retries
    #                         TRANSFER_GRIDFTP_RTINTERVAL : int = 60, # Interval in seconds before retry                           
    #                         **kwrags
    #                         ):
    #     class gridftp: 
    #         numparallel = TRANSFER_GRIDFTP_NUMPARALLEL
    #         verbose = TRANSFER_GRIPFTP_VERBOSE
    #         numretries = TRANSFER_GRIDFTP_RETRIES
    #         retryinterval = TRANSFER_GRIDFTP_RTINTERVAL
    #         def __repr__(self): 
    #             return ('GRIDFTP CONFIGURATION ============\n'
    #                     f'gridftp.numparallel = {self.numparallel}\n'
    #                     f'gridftp.verbose = {self.verbose}\n'
    #                     f'gridftp.numretries = {self.numretries}\n'
    #                     f'gridftp.retryinterval = {self.retryinterval}\n' 
    #                     '=================================')
    #     return gridftp()


        
    
#%%
if __name__ == '__main__':
    import astropy.units as u
    from tcspy.utils import NightSession

    A = DataTransferManager()

    # Find the just-completed night's image folder(s) using the same UTCDATE-12h
    # convention the scheduler / image writer use. Anchor to (now - 1 day): when run
    # in the morning/daytime, NightSession(now) would resolve to the *upcoming* night,
    # so we step back one day to target the night that just ended.
    obsnight = NightSession(Time.now() - 1 * u.day).obsnight_ltc
    sunset_date  = (obsnight.sunset_civil     - 12 * u.hour).datetime.strftime('%Y-%m-%d')
    sunrise_date = (obsnight.sunrise_shutdown - 12 * u.hour).datetime.strftime('%Y-%m-%d')
    dates = list(dict.fromkeys([sunset_date, sunrise_date]))

    folders = sorted({os.path.dirname(f)
                      for d in dates
                      for f in glob.glob(os.path.join(A.source_homedir, 'image', f'*{d}*', '*.fits'))})

    if not folders:
        print(f'No tonight image folders found to transfer (dates checked: {dates}).')
    for folder in folders:
        key = os.path.relpath(folder, A.source_homedir)
        print(f'Transferring: {key}')
        try:
            A.run(key = key, save_hash = False,
                  tar = True, transfer = True,
                  move_and_clean = True, from_archive = False)
            print(f'Transfer complete: {key}')
        except Exception as e:
            print(f'Transfer failed for {key}: {e}')

#%%
    # Background daemon mode (used by applications/monitoring.py) — NOT for a one-off
    # manual transfer (it loops forever). Uncomment to run the watch loop manually.
    # A.start_monitoring(
    #     ordinary_file_key='image/*',   # Adjust these parameters as needed
    #     ToO_file_key='image/*_ToO',
    #     inactivity_period=1800,             # 30 minutes of inactivity
    #     tar=True,                        # Compress files into tar
    #     protocol='hpnscp'               # File transfer protocol
    # )

#%%