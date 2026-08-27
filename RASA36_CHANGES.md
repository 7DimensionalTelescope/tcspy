# tcspy → RASA36: Customization Summary

**Author:** YoungPyo Hong
**Period:** February – April 2026
**Branch:** `RASA36` (forked from upstream `main` @ `250327_lyman`, Mar 2025)
**Target instrument:** single RASA36 telescope, `unitnum=36`

---

## 1. Context & Goal

The upstream tcspy was built to operate the **7DT array** — up to 16 telescopes
(`7DT01`–`7DT16`) coordinated by a Main Control System. This work forks that
codebase and re-engineers it into a focused control system for a **single
RASA36 telescope**, while modernizing three subsystems that RASA36 operations
depend on: the **focuser** (now driven through NINA), the **Target-of-Opportunity
(ToO) alert pipeline** (now Gmail API + Google Cloud Pub/Sub push), and the
**nightly scheduler/reporting** loop.

---

## 2. Scope & Scale

| Metric | Value |
|---|---|
| Commits on the RASA36 branch | 3 (Feb 3 2026 ×2, Apr 21 2026 ×1) |
| Python source files changed | ~52 |
| Net source change (code only) | **+4,278 / −1,718 lines** |
| New modules written from scratch | 5 (NINA client, NINA focuser, monitoring app, RASA36 DB loader, tile tooling) |
| Per-telescope config sets | 16 (`7DT01`–`7DT16`) → **1** (`RASA36`) |

> Note: the raw commit diffstat is much larger (641 files, +11.5k/−2.8k) because
> it also includes log files, FITS-derived images, tile data tables, and removed
> caches. The numbers above isolate the actual **code** changes.

### Largest individual code reworks

| File | ~Lines changed | Theme |
|---|---|---|
| `applications/appscheduler.py` | 577 | Scheduler overhaul + night reporting |
| `utils/alertmanager/alertmonitor.py` | 514 | ToO alert scheduling/safety |
| `devices/focuser/test_nina_api.py` | 507 | NINA focuser test harness |
| `utils/datatransfer.py` | 455 | Image-transfer rewrite |
| `utils/alertmanager/alertbroker.py` | 409 | Gmail push / Pub/Sub |
| `applications/startup.py` | 360 | Single-telescope startup |
| `devices/focuser/mainfocuser_nina.py` | 357 | New NINA focuser driver |
| `applications/nightobservation.py` | 321 | Rapid-ToO night loop |
| `utils/databases/DB_dynamic.py` | 288 | Renamed/reworked nightly DB |
| `utils/connector/gmailconnector.py` | 261 | Gmail API migration |

---

## 3. Single-Telescope Repackaging

- **Collapsed the multi-telescope config tree.** Removed the 16 per-telescope
  directories (`configuration/7DT01` … `7DT16`) and replaced them with a single
  **`configuration/RASA36/`** profile loaded for `unitnum=36`.
- **Retargeted instrument parameters** in `configuration/mainconfig.py`:
  - Camera pixel size `3.76 µm → 9 µm` (RASA36 detector).
  - Focuser device type `PWI4 → NINA`.
  - Observer name and Slack default/alert channels updated to the RASA36 setup.
- **RASA36 device endpoints** (new `configuration/RASA36/*.config`):
  - Camera (Alpaca): `10.0.106.22:11111`, device 0, 9 µm pixels.
  - Focuser (NINA): `10.0.106.22:1888`, travel range `5000–50000` steps.
- **Dependency modernization** in `requirements.txt`:
  `alpaca 1.0.0 → alpyca 3.1.2` (the maintained ASCOM Alpaca Python library).

---

## 4. NINA Focuser Integration *(new capability)*

RASA36's focuser is controlled through PlaneWave's NINA application rather than
ASCOM/PWI4, so a complete NINA control path was added:

- **`devices/nina_client.py` (new):** a thin HTTP client for the NINA Advanced
  API (`/v2/api/equipment/focuser`, port 1888) — connect, move, info, and
  autofocus endpoints.
- **`devices/focuser/mainfocuser_nina.py` (new, ~357 lines):** a full focuser
  driver implementing the same interface as the Alpaca/PWI4 focusers
  (`connect`, `disconnect`, `move`, `get_status`, `fans_on/off`, `wait_idle`)
  **plus NINA-native autofocus** (`autofocus_start`, last-AF-timestamp tracking).
- **Dispatch wiring** in `devices/singletelescope.py`: the focuser factory now
  resolves three device types — `Alpaca | PWI4 | NINA`.
- **`devices/focuser/test_nina_api.py` (new, ~507 lines):** an interactive
  `#%%`-cell test harness for validating the NINA API against the hardware.

---

## 5. ToO Alert Pipeline — Gmail API + Cloud Pub/Sub Push *(major modernization)*

The Target-of-Opportunity ingestion path (Gmail → parse → Slack → DB) was
rebuilt to react to alerts in near-real-time via **push notifications** instead
of periodic mailbox polling.

- **`utils/connector/gmailconnector.py` (rewritten, +261):** migrated to the
  **Gmail API** service (`_build_service`, `get_new_messages`, `_parse_message`,
  `_extract_body`, `send_mail` with attachments). Adds a **Pub/Sub watch**
  (`setup_watch`, `_renew_watch_loop`, `poll_pubsub`) so new mail triggers a
  push rather than a poll.
- **`utils/alertmanager/alertbroker.py` (+409):** new push plumbing
  (`setup_push`, `poll_pubsub`, `read_mail_push`) and split Gmail
  sender/receiver setup.
- **`utils/alertmanager/alertmonitor.py` (+514):** smarter dispatch —
  `trigger_alert`, a pending-alert queue (`_monitor_pending_alerts`), and
  **observability gating** before acting on an alert: `_is_safe()` (weather/
  safety monitor), `_is_nighttime()`, and `_compute_scheduled_time()` so ToOs
  are queued for a valid observing window. Also adds Slack/email status updates
  (`update_alertstatus`, `check_new_mail_push`).
- **`utils/alertmanager/alert.py` (+219):** reworked alert model/parsing.

---

## 6. Standalone Monitoring Process *(new)*

- **`applications/monitoring.py` (new):** a long-running background process that
  runs `AlertMonitor` (the ToO pipeline above) and `DataTransferManager` in
  daemon threads, independent of the nightly scheduler. Includes a `_TeeOutput`
  helper that mirrors all `print()` output to a **daily-rotating log file**
  (`/home/snu/code/RASA36/log/monitor_log/`) using the same −12 h "night date"
  offset as `mainLogger`, plus signal handling for clean shutdown.

---

## 7. Nightly Scheduler Overhaul — `applications/appscheduler.py` (+577)

- **Automated night-summary reporting:**
  - `_find_tonight_images()` / `_fits_to_png()` — locate and render the night's
    frames.
  - `_post_sample_image()` — post representative (e.g. first/last) frames to Slack.
  - `_generate_sky_coverage_plot()` — render a Mollweide sky-coverage map of the
    tiles observed tonight. Tiles that can never be selected under the survey
    cuts in `DB_Annual.select_best_targets` are shaded gray ("Excluded by
    cuts"), and the title reports progress against both the selectable pool
    (703/1319-style) and the full table. The cut limits (`TARGET_GALACTIC_
    LATITUDE_LIMIT`, `TARGET_DECLINATION_UPPER_LIMIT`,
    `TARGET_DECLINATION_LOWER_LIMIT`, default `0`/`20`/`−90`) live in
    `configuration/target.config`; both the plot code and
    `select_best_targets` read the same keys, so there is nothing left to
    manually keep in sync.
  - `_post_night_summary()` — assemble and publish the end-of-night report.
- **New pipeline stages:** `run_db_dynamic()` (refresh the nightly target DB) and
  `run_data_transfer()` (kick off archive transfer) as schedulable steps.
- **Operational robustness:** `dummy_run()` dry-run mode and a SIGINT handler
  (`_sigint_handler`) for graceful interruption.

---

## 8. Night Observation & Rapid ToO — `applications/nightobservation.py` (+321)

- Added a **rapid-ToO observation path** (`_rapidToOobservation`) so high-priority
  alerts can interrupt the regular survey cadence.
- Restructured initialization and the nightly loop for single-telescope dispatch.
- Reworked the level-2 observation sequence in
  `action/level2/singleobservation.py` (+166) and the V-curve autofocus in
  `action/level2/autofocus.py` (+92) to match the NINA focuser and RASA36 optics.

---

## 9. Database Layer & RASA36 Tiling

- **Renamed and reworked** `DB_daily.py → DB_dynamic.py` (+288) — the nightly,
  per-target scored table — and updated `DB_annual.py` (+218), the static
  target table.
- **`utils/databases/load_RASA36.py` (new):** populates the MySQL `TOS` table
  from RASA36 tile definitions — reads `displaycenter.txt`, assigns `T#####`
  object names, sets default exposure/filter/cadence columns, then computes
  rise/best/set dates via `DB_Annual.initialize()`.
- **RASA36 tile/footprint system (new, under `tileinfo/RASA36/`):**
  - `make_final_tiles.py` — computes per-tile centroids (circular-mean RA to
    handle the 0/360° wrap) from center + footprint tables.
  - `visualize_tiles.py` + generated all-sky/zoom PNGs for QA.
  - `utils/pointing_test.py` / `pointing_test_visualize.py` — pointing-accuracy
    checks.
- **`utils/connector/SQLconnector.py` (+132):** added bulk operations
  (`execute_many`, `bulk_update_rows`) for efficient nightly DB updates.

---

## 10. Image Transfer Rewrite — `utils/datatransfer.py` (+455)

- Reworked `DataTransferManager` with separate handling for **ordinary** vs
  **ToO** frames (`transfer_ordinary_files`, `transfer_ToO_files`), an
  inactivity-based trigger for ToO bundles, and a unified `start_monitoring()`
  loop supporting hashing, `tar` bundling, and `hpnscp` transfer to the archive.
- Integrated Slack notifications for transfer status (`_set_slack`).

---

## 11. Device Layer & Calibration Tuning

- **Camera** (`devices/camera/maincamera.py`, +202) — adapted to the RASA36
  detector and Alpaca endpoint.
- **Mounts** (`mainmount_alpaca.py`, `mainmount_pwi4.py`) and **observer**
  (`mainobserver.py`) — minor RASA36 adjustments.
- **Startup/Shutdown** (`startup.py` +360, `shutdown.py` +207) and the
  **calibration pipelines** (bias / dark / flat acquisition, `autoflat.py`)
  reworked for single-telescope sequencing.

---

## 12. Commit History

| Date | Commit | Summary |
|---|---|---|
| 2026-02-03 | `dfadb1ac5` | Initialize: built new branch for RASA36 |
| 2026-02-03 | `3dcd6fde8` | chore: update `.gitignore`, remove tracked Python caches |
| 2026-04-21 | `4190054b0` | rebuild: customize tcspy for RASA36 |

---

## 13. Current State / Next Steps

A substantial portion of the most recent work — the alert pipeline, the
scheduler reporting, the monitoring process, the NINA focuser, and the tile
tooling — is currently in the **working tree (uncommitted)**: ~54 modified
tracked files plus several new untracked files (`applications/monitoring.py`,
`utils/databases/load_RASA36.py`, the `tileinfo/RASA36/` scripts, pointing
tests). Committing this batch would align the Git history with the summary above
and make it a clean, citable record of the RASA36 implementation.

---

*Generated from Git history and working-tree diffs against the fork base
`250327_lyman` (`236304efb`).*
