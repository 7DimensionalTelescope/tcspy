# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

TCSpy (Telescope Control System with Python) is an astronomical observatory control system for managing multiple telescopes via network-based communication. It controls ASCOM Alpaca devices (camera, filter wheel, focuser, mount) and optionally PWI4 (PlaneWave) or NINA-based devices. The current branch (`RASA36`) is customized for a single RASA36 telescope instrument with `unitnum=36`: camera via Alpaca, mount via PWI4, focuser via NINA. See `RASA36_CHANGES.md` for a detailed summary of how this branch diverges from the upstream 7DT-array codebase.

The system runs on a Main Control System (MCS) computer that coordinates Telescope Control System (TCS) computers, each connected to a physical telescope over a local network.

## Installation

```bash
pip install -r requirements.txt
pip install -e .
```

The package installs itself as `tcspy`. Config files live in `configuration/` and are loaded at runtime — no build step required.

## Running the System

The system is a hardware control system, not a server — it is run as scripts or interactively. There is no automated test suite (no pytest). Manual testing is done by running `#%%`-cell scripts (Spyder/VSCode interactive cells) against real or simulated hardware.

**Main entry points:**
```bash
# Nightly scheduler (run on MCS)
python applications/appscheduler.py

# Background monitoring (alert broker + data transfer)
python applications/monitoring.py
```

**Interactive testing (using `#%%` cells in a script):**
```python
from tcspy.devices import SingleTelescope
from tcspy.action.level1 import *
from multiprocessing import Event

tel = SingleTelescope(36)           # unitnum=36 for RASA36
abort_action = Event()
Connect(tel, abort_action).run()
Exposure(tel, abort_action).run(frame_number=1, exptime=10, filter_='g', imgtype='Light')
```

The test scripts in `action/test.py` and `action/level1/test.py` are example cell notebooks for interactive use.

## Configuration System

All configuration is loaded via `configuration/mainConfig`. It reads `*.config` JSON files from two places:

1. `configuration/*.config` — global params (observer, DB, Gmail, Slack, alert broker, autofocus, etc.)
2. `configuration/<TEL_NAME>/*.config` — per-telescope params (camera, mount, focuser, filter wheel, logger, image paths)

`TCSpy.config` must exist at the global path or a `RuntimeError` is raised. `TCSPY_TEL_NAME` is `"RASA"` for this branch; `unitnum=36` produces `tel_name = "RASA36"`, loading from `configuration/RASA36/`.

To initialize fresh config files for a unit:
```python
from tcspy.configuration import mainConfig
A = mainConfig(unitnum=36)
A._initialize_config(ip_address='<TCS_IP>', portnum=11111)
```

RASA36 runtime data paths (from `*.config` files):
- Images/logs: `/home/snu/code/RASA36/image/`, `/home/snu/code/RASA36/log/`
- DB history / sync: `/home/snu/RASA36/DB_history`, `/home/snu/RASA36/sync/`
- Alert history: `/home/snu/code/RASA36/alert_history/`

## Architecture

### Device Layer (`devices/`)

- `SingleTelescope` — aggregates all physical devices for one telescope: camera, mount, focuser, filter wheel, weather, safety monitor, observer. Mount and focuser types are determined by config keys `MOUNT_DEVICETYPE` (`Alpaca` or `PWI4`) and `FOCUSER_DEVICETYPE` (`Alpaca`, `PWI4`, or `NINA`).
- `MultiTelescopes` — holds a dict of `SingleTelescope` instances; loads telescope list from `MULTITELESCOPES_FILE` config if no list is passed explicitly.
- `TelescopeStatus` — queries device status across a `SingleTelescope`.
- `NINA` (`devices/nina_client.py`) — HTTP client for NINA Advanced API (port 1888), used for focuser control.
- `PWI4` (`devices/pwi4_client.py`) — HTTP client for PlaneWave PWI4 API.

Each device type lives in its own subdirectory under `devices/` (e.g., `devices/camera/`, `devices/focuser/`, `devices/mount/`, `devices/filterwheel/`, `devices/weather/`, `devices/safetymonitor/`). Device classes are named `mainCamera`, `mainFocuser_Alpaca`, `mainFocuser_pwi4`, `mainFocuser_NINA`, `mainMount_Alpaca`, `mainMount_pwi4`, etc.

### Action Layer (`action/`)

Three hierarchical levels, each composed from the level below:

- **Level 1** (`action/level1/`) — atomic single-device commands: `Connect`, `Disconnect`, `Exposure`, `ChangeFocus`, `ChangeFilter`, `SlewRADec`, `SlewAltAz`, `Cool`, `Warm`, `Park`, `Home`, `TrackingOn`, `TrackingOff`, `FansOn`, `FansOff`, `Unpark`.
- **Level 2** (`action/level2/`) — single-telescope coordinated sequences: `SingleObservation` (slew + filter change + autofocus + expose), `AutoFocus` (V-curve focus), `AutoFlat`.
- **Level 3** (`action/level3/`) — multi-telescope observation modes: `ColorObservation`, `DeepObservation`, `SpecObservation`.

`MultiAction` (`action/multiaction.py`) runs any action in parallel across a list of `SingleTelescope` instances using `multiprocessing.Process`.

All action classes implement `Interface_Runnable` and `Interface_Abortable` from `interfaces/`. Each action holds a `shared_memory` (a `multiprocessing.Manager().dict()`) with keys `succeeded`, `exception`, `exception_message`, and `is_running`.

Abort flow: every action accepts an `abort_action: multiprocessing.Event`. Calling `.abort()` sets this event and the action's `.run()` loop checks it.

### Application Layer (`applications/`)

High-level nightly operations orchestrated by `AppScheduler`:

- `Startup` / `Shutdown` — telescope connect, cool, home, park sequences.
- `BiasAcquisition`, `DarkAcquisition`, `FlatAcquisition` — calibration frame pipelines.
- `NightObservation` — the main nightly loop: consumes targets from the DB, dispatches observations, monitors weather, and handles ToO interrupts including a rapid-ToO path (`_rapidToOobservation`) that preempts the regular survey cadence.
- `AppScheduler` — top-level scheduler that sequences the nightly pipeline using the `schedule` library. Also refreshes the nightly DB (`run_db_dynamic`), kicks off archive transfer (`run_data_transfer`), and posts an end-of-night Slack report (sample images + sky-coverage plot). Has a `dummy_run()` dry-run mode for testing the schedule without hardware.
- `monitoring.py` — standalone background process: runs `AlertMonitor` (Gmail → Slack ToO pipeline) and `DataTransferManager` in daemon threads.

### Utility Layer (`utils/`)

- `databases/` — `DB` wraps `DB_Dynamic` (nightly MySQL target table, scored per target) and `DB_Annual` (static TOS table). `DB_Dynamic` connects via `SQLConnector` to MySQL.
- `target/` — `SingleTarget` and `MultiTargets`: wrap astroplan/astropy for observability scoring, rise/set/transit times, altitude constraints, moon separation.
- `alertmanager/` — `AlertBroker` + `AlertMonitor`: receive ToO alert mail via the Gmail API with Google Cloud Pub/Sub push notifications (near-real-time, not polling), parse alerts, post to Slack, and inject targets into `DB_Dynamic`. `AlertMonitor` gates dispatch on observability (`_is_safe()`, `_is_nighttime()`) and queues pending alerts for a valid observing window.
- `connector/` — `SlackConnector`, `GmailConnector` (Gmail API service + Pub/Sub watch renewal), `SQLConnector` (MySQL via `mysql_connector_repackaged`, with bulk operations `execute_many` / `bulk_update_rows`).
- `logger/mainLogger` — file-based rotating logger, inherits `mainConfig`, used throughout actions and applications.
- `error/` — device-layer exceptions (e.g., `FocuserTypeError`, `DBConnectionError`).
- `exception/` — action-layer exceptions (e.g., `AbortionException`, `ExposureFailedException`, `AutofocusFailedException`, `DeviceNotReadyException`). All action `.run()` methods raise these on failure and store them in `shared_memory['exception']`.
- `NightSession` — computes sunset/sunrise/twilight times for tonight's session from observer config.
- `DataTransferManager` — hpnscp/rsync/GridFTP transfer of image data to the archive server.
- `Timeout` — context manager for time-bounded loops.

### Configuration models (`configuration/`)

- `mainConfig` — base class inherited by nearly every class in the system; loads all `.config` JSON files into `self.config` dict.
- `FocusModel` (`configuration/focusmodel.py`) — polynomial focus model per filter.

## Key Patterns

**Inheritance from mainConfig**: Almost every class inherits `mainConfig` so it can access `self.config` and `self.tel_name` directly. When subclassing, always call `super().__init__(unitnum=unitnum)`.

**Multiprocessing for parallelism**: `MultiAction.run()` launches one `Process` per telescope. Actions use `multiprocessing.Event` for abort signaling and `Manager().dict()` for shared results.

**Exception flow in actions**: Actions catch hardware failures, store the exception in `shared_memory['exception']`, set `shared_memory['succeeded'] = False`, and re-raise. `AbortionException` is raised when `abort_action` is set mid-run.

**Shared status files**: `MultiTelescopes.update_statusfile()` writes a JSON status dict guarded by `portalocker` — used for inter-process coordination between the scheduler and any monitoring process.

**Autofocus history**: Focus positions are persisted to `configuration/<TEL_NAME>/focus_history.json` (path from `AUTOFOCUS_FOCUSHISTORY_PATH` config key) and reused within `AUTOFOCUS_TOLERANCE` steps to skip redundant refocusing.

**Interactive development**: Scripts throughout the codebase use `#%%` cell delimiters for Spyder/VSCode interactive execution. This is the primary development and hardware-testing workflow — not pytest.

## Verifying Changes Without Hardware

There is no test suite, and the real test happens at night on live hardware — so a change that fails offline checks costs an observing night. After ANY code change, climb this ladder as far as the change allows (the `verify` project skill automates it):

1. **Syntax**: `python -m py_compile <every edited .py file>`
2. **Imports**: `python -c "import tcspy.<module.path>"` for every touched module (catches circular imports and missing names).
3. **Config keys**: if you added/renamed a config key, confirm it loads:
   `python -c "from tcspy.configuration import mainConfig; c = mainConfig(unitnum=36).config; print(c['<KEY>'])"`
4. **Call sites**: before changing any function signature or renaming anything, `grep -rn` every call site across the repo and update all of them in the same change.
5. **Scheduler changes**: run `AppScheduler.dummy_run()` — it exercises the nightly schedule without hardware.
6. **ToO/alert-path changes**: inject a fake alert without Gmail via `AlertBroker.read_tbl` + `AlertMonitor.trigger_alert` (see the `test-too` skill). Never test through the live DB on an observing night.
7. **Performance claims**: measure with a scratchpad micro-benchmark; don't assert speedups you didn't time.

A running process does NOT pick up code edits — `.py` changes require a restart of `appscheduler.py`/`monitoring.py`. Config `.config` JSON is re-read whenever a `mainConfig`-derived object is instantiated, so pure config changes usually take effect on the next cycle without restart. Always tell the operator which of the two applies to your change.

## Operational Red Lines

- **Never write to the live MySQL target table (`DB_Dynamic`) on an observing night.** A fake rapid-ToO row will preempt real observations. Use the fake-alert injection path instead.
- **Never hand-edit `configuration/<TEL_NAME>/focus_history.json`** — it is written by `AutoFocus` and validated against; a bogus value silently mis-focuses the whole night.
- **Every blocking loop must poll `abort_action`.** Any new `while`/wait you add inside an action or application must check `abort_action.is_set()` each iteration and raise `AbortionException`.
- **New config keys must be backward compatible**: read them as `self.config.get('KEY', legacy_default)` so a missing key reproduces the old behavior exactly. Add the key to the `.config` JSON as well.
- **Preserve the `shared_memory` contract** in actions: on failure set `succeeded=False`, store the exception in `exception`, and re-raise.
- **Slack/Gmail side effects are live.** Code paths that post to Slack or send mail will really post; guard test runs accordingly.

## Log Triage Map

Most sessions start from a pasted log. Logs live in `/home/snu/code/RASA36/log/` (nightly, `YYYYMMDD.log`) and `/home/snu/code/RASA36/log/monitor_log/` (from `monitoring.py`). Common lines and their owners:

| Log line | Owner | Start here |
|---|---|---|
| `Waiting for ordinary observation aborted...` | ToO interrupt preempting survey | `applications/nightobservation.py` (~line 628) |
| `Best target: (...)` | Target selection loop | `applications/nightobservation.py`, `DB.best_target()` |
| `[<AppName>] is triggered.` / `is finished.` | Scheduler stage transitions | `applications/appscheduler.py` + the named app |
| `Calculating celestial information of N targets...` / `0/N targets are updated` | Nightly DB scoring | `utils/databases/DB_dynamic.py` (~line 141) |
| `[initialize] SingleTarget failed for shared params: ...` | Bad target row (e.g. unregistered specmode) | `utils/databases/DB_dynamic.py` (~line 180), `utils/target/singletarget.py` |
| `Specmode : X is not registered` / `Colormode : ...` | Mode folder lookup | `utils/target/singletarget.py` (~line 615), `SPECMODE_FOLDER` config |
| `Autofocus position N ... Rejecting result.` | Focus validation | `action/level2/autofocus.py` `_is_focusval_valid` (~line 410) |
| `Monitoring started.` | Alert/transfer daemon startup | `applications/monitoring.py` |
| `Data transfer complete — ...` (Slack) | Archive transfer | `utils/datatransfer.py` (~line 234) |

When triaging: identify the owning module from this table first, diagnose the root cause, and report it **before** proposing an edit (the `triage-log` skill walks through this).

## Before Editing Operational Files

`applications/nightobservation.py`, `applications/appscheduler.py`, `utils/alertmanager/*`, and everything under `devices/` run unattended against real hardware at night. For changes to these files: state the intended behavior change and the exact spots you will touch, and get the operator's confirmation (or use plan mode) **before** editing. Small, reviewable diffs; no drive-by refactors in these files.

## Session Discipline

- **Persist operator decisions.** When the operator makes a policy decision (e.g. "rapid ToO skips autofocus") or reveals a hardware fact (e.g. the true RASA36 focus range), save it to auto-memory before the session ends — future sessions must not re-ask.
- **Onboard from docs, not exploration.** `RASA36_CHANGES.md` explains how this branch diverges from upstream; read it instead of re-deriving the fork history.
- **Keep sessions scoped.** One subsystem per session where possible; long infra-setup sessions exhaust context and lose state.
