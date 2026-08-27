import argparse
import uuid
from datetime import datetime, date
from zoneinfo import ZoneInfo

import numpy as np
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.table import Table
from astropy.time import Time

from tcspy.configuration import mainConfig
from tcspy.utils.databases.DB_dynamic import DB_Dynamic


class PointingTest(mainConfig):
    """
    Insert mount tracking/pointing diagnostic targets into DB_Dynamic.

    Two groups are created:
    - Grid: 2-D (RA, Dec) grid at 5-second exposures, filtered to altitude > min_alt
      at local midnight on test_date.
    - Exptime sweep: six exposures at the worst-case position (Dec +10°, 4 h east of
      meridian) to test whether the issue scales with exposure duration.

    Run *before* AppScheduler. Targets are assigned priority=1 so the scheduler
    always picks them ahead of normal TOS/IMS targets (default priority=50).
    """

    def __init__(self, unitnum: int = 1, test_date: date = None,
                 obs_time: Time = None):
        super().__init__(unitnum=unitnum)
        self._tz = ZoneInfo(self.config['OBSERVER_TIMEZONE'])
        self._location = EarthLocation(
            lat=self.config['OBSERVER_LATITUDE'] * u.deg,
            lon=self.config['OBSERVER_LONGITUDE'] * u.deg,
            height=self.config['OBSERVER_ELEVATION'] * u.m,
        )
        if test_date is None:
            test_date = date.today()
        midnight_local = datetime(test_date.year, test_date.month, test_date.day,
                                  0, 0, 0, tzinfo=self._tz)
                                  
        self.midnight_utc = Time(midnight_local)
        self.lst_midnight = self.midnight_utc.sidereal_time(
            'apparent', longitude=self._location.lon
        )
        # obs_time controls which LST is used for transit-RA calculations.
        # Defaults to now so that targets are centred on the current meridian.
        self.obs_time = obs_time if obs_time is not None else Time.now()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_altitude(self, ra_deg: float, dec_deg: float,
                     time: Time = None) -> float:
        if time is None:
            time = self.midnight_utc
        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame='icrs')
        altaz = coord.transform_to(
            AltAz(obstime=time, location=self._location)
        )
        return float(altaz.alt.deg)

    def _clear_previous_test_targets(self, db: DB_Dynamic) -> int:
        all_data = db.data
        if len(all_data) == 0:
            return 0
        mask = all_data['objtype'] == 'Test'
        ids = list(all_data['id'][mask])
        if ids:
            db.sql.remove_rows(tbl_name=db.tblname, ids=ids)
            print(f'[pointing_test] Removed {len(ids)} old Test targets from DB.')
        return len(ids)

    def _make_target(self, objname: str, ra: float, dec: float,
                     exptime: float, count: int, note: str) -> dict:
        return dict(
            id=uuid.uuid4().hex,
            objname=objname,
            RA=float(ra),
            De=float(dec),
            exptime=float(exptime),
            count=int(count),
            filter_='r',
            obsmode='Single',
            binning=1,
            gain=25,
            ntelescope=1,
            objtype='Test',
            priority=1,
            weight=1.0,
            is_rapidToO=0,
            note=note,
        )

    # ------------------------------------------------------------------
    # Target generators
    # ------------------------------------------------------------------

    def generate_grid_targets(self,
                              ra_step: float = 10.0,
                              dec_step: float = 10.0,
                              min_alt: float = 20.0) -> list:
        """2-D (RA, Dec) grid expanding outward from the current transit RA (LST).

        Hour-angle offsets grow symmetrically from HA=0 (meridian), so targets
        closest to transit — highest altitude, lowest airmass — appear first.
        If the scheduler cannot finish all targets, the best ones are observed first.

        HA > 0 → west of meridian (setting); HA < 0 → east of meridian (rising).
        RA = LST - HA.
        """
        lst_now = self.obs_time.sidereal_time('apparent', longitude=self._location.lon)
        lst_deg = lst_now.deg

        # Build HA offsets expanding from HA=0 outward: 0, +step, -step, +2*step, ...
        # Stop before ±180 deg — both map to the same anti-meridian RA.
        n_steps = int(180 / ra_step)
        ha_offsets = [0.0]
        for i in range(1, n_steps + 1):
            ha_offsets.append(i * ra_step)
            if i * ra_step < 180:
                ha_offsets.append(-i * ra_step)

        dec_values = np.arange(-90, 91, dec_step)

        targets = []
        for ha_deg in ha_offsets:
            ra = (lst_deg - ha_deg) % 360
            for dec in dec_values:
                alt = self._get_altitude(ra, dec, time=self.obs_time)
                if alt > min_alt:
                    targets.append(self._make_target(
                        objname=f'TRACK_RA{ra:05.1f}_D{dec:+05.1f}',
                        ra=ra, dec=dec,
                        exptime=10.0, count=1,
                        note=(f'pointing_grid LST={lst_deg:.1f}deg '
                              f'HA={ha_deg:+.1f}deg alt={alt:.1f}deg'),
                    ))
        return targets

    def generate_exptime_targets(self,
                                 dec_deg: float = 10.0,
                                 exptimes: list = None) -> list:
        """Exposure-time sweep at Dec=10° on the meridian for best SNR.

        RA is set to LST so the target is at transit — the highest possible altitude
        for Dec=10°, minimising airmass and maximising SNR.
        """
        if exptimes is None:
            exptimes = [0.01, 0.1, 0.5, 1.0, 5.0, 10.0]
        lst_now = self.obs_time.sidereal_time('apparent', longitude=self._location.lon)
        ra_deg = lst_now.deg  # meridian transit → maximum altitude for dec_deg
        alt = self._get_altitude(ra_deg, dec_deg, time=self.obs_time)
        targets = []
        for exptime in exptimes:
            targets.append(self._make_target(
                objname=f'EXPTEST_exp{exptime}s',
                ra=ra_deg, dec=dec_deg,
                exptime=exptime, count=3,
                note=f'exposure_sweep transit alt={alt:.1f}deg dec={dec_deg:.1f}deg',
            ))
        return targets

    # ------------------------------------------------------------------
    # DB insertion
    # ------------------------------------------------------------------

    def insert_to_db(self, targets: list, db: DB_Dynamic):
        tbl = Table(rows=targets)
        result = db.insert(tbl)
        n_ok = sum(1 for r in result if r)
        print(f'[pointing_test] Inserted {n_ok}/{len(targets)} targets.')
        print('[pointing_test] Initialising observability data...')
        db.initialize()
        return result

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, dry_run: bool = False):
        print(f'\n=== PointingTest ===')
        print(f'  Midnight UTC : {self.midnight_utc.iso}')
        print(f'  LST@midnight : {self.lst_midnight.to_string(sep=":", precision=1)}')
        transit_ra = self.obs_time.sidereal_time('apparent', longitude=self._location.lon).deg
        transit_local = self.obs_time.to_datetime(timezone=self._tz)
        print(f'  Transit time : {self.obs_time.iso} UTC  /  {transit_local.strftime("%Y-%m-%d %H:%M:%S")} local')
        print(f'  Transit RA   : {transit_ra:.4f} deg  ({transit_ra / 15:.4f} h)')
        print()
        print(f'  Observatory  : lat={self.config["OBSERVER_LATITUDE"]}°  '
              f'lon={self.config["OBSERVER_LONGITUDE"]}°')

        grid = self.generate_grid_targets()
        exptime = self.generate_exptime_targets()
        all_targets = grid + exptime

        # Print target summary table
        header = f'{"Name":<35} {"RA":>7} {"Dec":>6} {"Alt":>6} {"Exp":>6} {"N":>3}'
        print(f'\n{header}')
        print('-' * len(header))
        for t in all_targets:
            alt = self._get_altitude(t['RA'], t['De'])
            print(f'{t["objname"]:<35} {t["RA"]:7.2f} {t["De"]:6.2f} '
                  f'{alt:6.1f} {t["exptime"]:6.3f} {t["count"]:3d}')

        print(f'\n  Grid targets : {len(grid)}')
        print(f'  Exptime targets : {len(exptime)}')
        print(f'  Total        : {len(all_targets)}')

        if dry_run:
            print('\n[DRY RUN] No changes written to DB.')
            return

        db = DB_Dynamic()
        self._clear_previous_test_targets(db)
        self.insert_to_db(all_targets, db)
        print('[pointing_test] Done.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Insert mount pointing/tracking test targets into DB_Dynamic.'
    )
    parser.add_argument('--unitnum', type=int, default=1)
    parser.add_argument('--dry-run', action='store_true',
                        help='Print targets without writing to DB.')
    parser.add_argument('--date', type=str, default=None,
                        help='Test date YYYY-MM-DD (default: today).')
    parser.add_argument('--time', type=str, default=None,
                        help='Transit reference time in UTC, e.g. "2026-06-05 21:30:00" '
                             '(default: now). Determines which LST — and thus which RA — '
                             'is at the meridian when building the target grid.')
    args = parser.parse_args()

    test_date = None
    if args.date:
        test_date = date.fromisoformat(args.date)

    obs_time = None
    if args.time:
        obs_time = Time(args.time, scale='utc')

    pt = PointingTest(unitnum=args.unitnum, test_date=test_date, obs_time=obs_time)
    pt.run(dry_run=args.dry_run)
