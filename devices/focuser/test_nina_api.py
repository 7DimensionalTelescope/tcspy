#%%
"""
NINA Focuser API Behavior Test (standalone)
============================================
Purpose: Observe raw NINA API responses at each stage to understand:
  1. Response structure of each endpoint
  2. How /info changes during movement and autofocus
  3. How /last-af changes before, during, and after autofocus
  4. Edge cases (cancel when idle, double-start, etc.)

Requirements: Python 3.6+ (standard library only, no tcspy needed)

Equivalent curl commands for reference:
  curl http://HOST:PORT/v2/api/equipment/focuser/info
  curl http://HOST:PORT/v2/api/equipment/focuser/connect
  curl http://HOST:PORT/v2/api/equipment/focuser/disconnect
  curl http://HOST:PORT/v2/api/equipment/focuser/list-devices
  curl http://HOST:PORT/v2/api/equipment/focuser/move?position=5000
  curl http://HOST:PORT/v2/api/equipment/focuser/auto-focus
  curl http://HOST:PORT/v2/api/equipment/focuser/auto-focus?cancel=true
  curl http://HOST:PORT/v2/api/equipment/focuser/last-af

Usage:
  - NINA must be running with a focuser connected
  - Adjust HOST / PORT below to match your setup
  - Run each cell sequentially in IPython / Jupyter, or run the whole file
"""

import json
import time
from datetime import datetime
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

# === CONFIGURATION ===
HOST = "10.0.106.22"
PORT = 1888
BASE_URL = f"http://{HOST}:{PORT}/v2/api/equipment/focuser"
POLL_INTERVAL = 1.0  # seconds between polls during autofocus
LOG_FILE = "nina_api_test_results.json"
TIMEOUT = 10  # HTTP request timeout in seconds

test_results = {}

# === HTTP helper (replaces tcspy NINA client) ===

def nina_get(endpoint, **params):
    """
    Send a GET request to NINA API. Same as:
      curl "http://HOST:PORT/v2/api/equipment/focuser{endpoint}?{params}"

    Returns parsed JSON dict, or raises Exception on error.
    """
    url = BASE_URL + endpoint
    if params:
        # Convert booleans to lowercase strings for URL
        clean = {k: str(v).lower() if isinstance(v, bool) else v
                 for k, v in params.items()}
        url += "?" + urlencode(clean)

    try:
        resp = urlopen(url, timeout=TIMEOUT)
        body = resp.read().decode('utf-8')
        return json.loads(body)
    except HTTPError as e:
        error_msg = f"HTTP {e.code}"
        try:
            error_body = json.loads(e.read().decode('utf-8'))
            error_msg = f"HTTP {e.code}: {error_body.get('Error', error_msg)}"
        except:
            pass
        raise Exception(error_msg)
    except URLError as e:
        raise Exception(f"Connection failed: {e.reason}")


def log_result(test_name, data):
    """Store and pretty-print a test result."""
    test_results[test_name] = {
        "timestamp": datetime.now().isoformat(),
        "data": data
    }
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, default=str))

def save_results():
    """Save all test results to JSON file."""
    with open(LOG_FILE, 'w') as f:
        json.dump(test_results, f, indent=2, default=str)
    print(f"\nResults saved to {LOG_FILE}")


#%% ============================================================
# PHASE 0: Connect to the focuser
# Must be done before any other operations
# ==============================================================

#%% Test 0-1: Connect
# curl http://HOST:PORT/v2/api/equipment/focuser/connect
print("Phase 0: Connect")
print("-" * 40)

try:
    result = nina_get("/connect")
    log_result("0-1_connect", result)
    # CHECK: Response should be "Connected"
    # CHECK: Success should be true
except Exception as e:
    log_result("0-1_connect", {"error": str(e)})

# Verify connection via /info
try:
    result = nina_get("/info")
    connected = result.get('Response', {}).get('Connected', False)
    print(f"  Connected: {connected}")
    if not connected:
        print("  WARNING: Focuser not connected. Remaining tests may fail.")
except Exception as e:
    print(f"  Could not verify connection: {e}")


#%% ============================================================
# PHASE 1: Static endpoint tests (no movement)
# Verify response shapes and baseline values
# ==============================================================

#%% Test 1-1: focuser_info (baseline)
# curl http://HOST:PORT/v2/api/equipment/focuser/info
print("\nPhase 1: Static endpoint tests")
print("-" * 40)

try:
    result = nina_get("/info")
    log_result("1-1_focuser_info_baseline", result)
    # CHECK: What keys are in Response?
    # CHECK: Is Connected = true?
    # CHECK: What is the current Position?
    # CHECK: IsMoving should be false
    # CHECK: IsSettling should be false
except Exception as e:
    log_result("1-1_focuser_info_baseline", {"error": str(e)})

#%% Test 1-2: last-af (baseline - before any autofocus)
# curl http://HOST:PORT/v2/api/equipment/focuser/last-af
try:
    result = nina_get("/last-af")
    log_result("1-2_last_af_baseline", result)
    # CHECK: Does Response exist? What keys does it contain?
    # CHECK: What is Timestamp value? (empty string? null? previous run?)
    # CHECK: What is CalculatedFocusPoint structure?
    # CHECK: What is MeasurePoints structure?
except Exception as e:
    log_result("1-2_last_af_baseline", {"error": str(e)})

#%% Test 1-3: Cancel autofocus when nothing is running
# curl "http://HOST:PORT/v2/api/equipment/focuser/auto-focus?cancel=true"
try:
    result = nina_get("/auto-focus", cancel=True)
    log_result("1-3_cancel_when_idle", result)
    # CHECK: Does this succeed or raise an error?
    # CHECK: What is the Response value?
except Exception as e:
    log_result("1-3_cancel_when_idle", {"error": str(e)})

#%% Test 1-4: list-devices
# curl http://HOST:PORT/v2/api/equipment/focuser/list-devices
try:
    result = nina_get("/list-devices")
    log_result("1-4_list_devices", result)
except Exception as e:
    log_result("1-4_list_devices", {"error": str(e)})


#%% ============================================================
# PHASE 2: Move test
# Verify /info response during focuser movement
# ==============================================================

#%% Test 2-1: Move and poll /info
print("\nPhase 2: Move test")
print("-" * 40)

try:
    # Get current position first
    info_before = nina_get("/info")
    current_pos = info_before['Response']['Position']
    target_pos = current_pos + 500  # Move 500 steps forward
    log_result("2-1a_position_before_move", {
        "current_position": current_pos,
        "target_position": target_pos
    })

    # Start the move
    # curl "http://HOST:PORT/v2/api/equipment/focuser/move?position=XXXX"
    move_result = nina_get("/move", position=target_pos)
    log_result("2-1b_move_command_response", move_result)

    # Poll /info during movement
    move_polls = []
    poll_count = 0
    max_polls = 60
    while poll_count < max_polls:
        time.sleep(POLL_INTERVAL)
        info = nina_get("/info")
        resp = info['Response']
        poll_entry = {
            "poll_num": poll_count,
            "time": datetime.now().isoformat(),
            "Position": resp['Position'],
            "IsMoving": resp['IsMoving'],
            "IsSettling": resp['IsSettling'],
        }
        move_polls.append(poll_entry)
        print(f"  Poll {poll_count}: pos={resp['Position']}, moving={resp['IsMoving']}, settling={resp['IsSettling']}")
        poll_count += 1

        if not resp['IsMoving'] and not resp['IsSettling']:
            break

    log_result("2-1c_move_polls", move_polls)
    # CHECK: Does Position update incrementally during move?
    # CHECK: IsMoving = true while moving, false when done?
    # CHECK: Does IsSettling become true after IsMoving goes false?

    # Move back to original position
    nina_get("/move", position=current_pos)
    print(f"  Moving back to original position: {current_pos}")
    time.sleep(5)

except Exception as e:
    log_result("2-1_move_test", {"error": str(e)})


#%% ============================================================
# PHASE 3: Autofocus test (MAIN TEST)
# Poll both /info and /last-af during autofocus
# ==============================================================

#%% Test 3-1: Record pre-autofocus state
print("\nPhase 3: Autofocus test")
print("-" * 40)

try:
    info_pre = nina_get("/info")
    last_af_pre = nina_get("/last-af")
    pre_state = {
        "info": info_pre,
        "last_af": last_af_pre,
        "last_af_timestamp": last_af_pre.get('Response', {}).get('Timestamp', 'N/A')
    }
    log_result("3-1_pre_autofocus_state", pre_state)
    pre_af_timestamp = pre_state["last_af_timestamp"]
    print(f"  Pre-AF timestamp: {pre_af_timestamp}")
except Exception as e:
    log_result("3-1_pre_autofocus_state", {"error": str(e)})
    pre_af_timestamp = None

#%% Test 3-2: Start autofocus and poll continuously
# curl http://HOST:PORT/v2/api/equipment/focuser/auto-focus
try:
    # Start autofocus
    af_start_result = nina_get("/auto-focus")
    af_start_time = datetime.now().isoformat()
    log_result("3-2a_autofocus_start_response", {
        "start_time": af_start_time,
        "response": af_start_result
    })
    # CHECK: What does the start response look like?

    # Poll both endpoints continuously
    af_polls = []
    poll_count = 0
    max_polls = 300  # 5 minutes at 1s interval
    af_finished = False

    while poll_count < max_polls and not af_finished:
        time.sleep(POLL_INTERVAL)

        # Poll /info
        try:
            info = nina_get("/info")
            info_resp = info['Response']
            info_data = {
                "Position": info_resp.get('Position'),
                "IsMoving": info_resp.get('IsMoving'),
                "IsSettling": info_resp.get('IsSettling'),
                "Connected": info_resp.get('Connected'),
            }
        except Exception as e:
            info_data = {"error": str(e)}

        # Poll /last-af
        try:
            last_af = nina_get("/last-af")
            last_af_resp = last_af.get('Response', {})
            last_af_data = {
                "Timestamp": last_af_resp.get('Timestamp'),
                "Temperature": last_af_resp.get('Temperature'),
                "Duration": last_af_resp.get('Duration'),
                "Method": last_af_resp.get('Method'),
                "CalculatedFocusPoint": last_af_resp.get('CalculatedFocusPoint'),
                "InitialFocusPoint": last_af_resp.get('InitialFocusPoint'),
            }
            current_af_timestamp = last_af_resp.get('Timestamp', '')
        except Exception as e:
            last_af_data = {"error": str(e)}
            current_af_timestamp = ''

        poll_entry = {
            "poll_num": poll_count,
            "time": datetime.now().isoformat(),
            "elapsed_sec": poll_count * POLL_INTERVAL,
            "info": info_data,
            "last_af": last_af_data,
            "timestamp_changed": current_af_timestamp != pre_af_timestamp,
        }
        af_polls.append(poll_entry)

        # Print condensed status
        pos = info_data.get('Position', '?')
        moving = info_data.get('IsMoving', '?')
        settling = info_data.get('IsSettling', '?')
        ts_changed = poll_entry['timestamp_changed']
        print(f"  [{poll_count:3d}] pos={pos}, moving={moving}, settling={settling}, "
              f"af_ts_changed={ts_changed}, af_ts={current_af_timestamp}")

        # Detect autofocus completion: timestamp changed
        if ts_changed and current_af_timestamp != '':
            af_finished = True
            print(f"\n  >>> Autofocus completed! New timestamp: {current_af_timestamp}")

        poll_count += 1

    log_result("3-2b_autofocus_polls", {
        "total_polls": len(af_polls),
        "af_finished_detected": af_finished,
        "polls": af_polls
    })

except Exception as e:
    log_result("3-2_autofocus_polling", {"error": str(e)})

#%% Test 3-3: Post-autofocus state
try:
    info_post = nina_get("/info")
    last_af_post = nina_get("/last-af")
    post_state = {
        "info": info_post,
        "last_af": last_af_post,
    }
    log_result("3-3_post_autofocus_state", post_state)

    # Extract key autofocus results
    af_resp = last_af_post.get('Response', {})
    print(f"\n  === Autofocus Results ===")
    print(f"  Timestamp:    {af_resp.get('Timestamp')}")
    print(f"  Temperature:  {af_resp.get('Temperature')}")
    print(f"  Method:       {af_resp.get('Method')}")
    print(f"  Fitting:      {af_resp.get('Fitting')}")
    print(f"  Duration:     {af_resp.get('Duration')}")
    calc = af_resp.get('CalculatedFocusPoint', {})
    print(f"  Best Position: {calc.get('Position')}")
    print(f"  Best HFR:      {calc.get('Value')}")
    init = af_resp.get('InitialFocusPoint', {})
    print(f"  Initial Pos:   {init.get('Position')}")
    print(f"  MeasurePoints: {len(af_resp.get('MeasurePoints', []))} points")
    print(f"  R-Squares:     {af_resp.get('RSquares')}")
except Exception as e:
    log_result("3-3_post_autofocus_state", {"error": str(e)})


#%% ============================================================
# PHASE 4: Edge case tests
# ==============================================================

#%% Test 4-1: Call autofocus_start while autofocus is already running
print("\nPhase 4: Edge case tests")
print("-" * 40)
print("Test 4-1: Double autofocus start")
print("  Starting first autofocus...")

try:
    result1 = nina_get("/auto-focus")
    log_result("4-1a_first_start", result1)
    time.sleep(3)  # Wait a few seconds

    print("  Starting second autofocus (while first is running)...")
    try:
        result2 = nina_get("/auto-focus")
        log_result("4-1b_second_start", result2)
        # CHECK: Does it error? Does it restart? Does it return success?
    except Exception as e:
        log_result("4-1b_second_start", {"error": str(e), "error_type": type(e).__name__})
        # CHECK: What error code / message?

    # Cancel to clean up
    time.sleep(2)
    cancel_result = nina_get("/auto-focus", cancel=True)
    log_result("4-1c_cancel_after_double_start", cancel_result)
    time.sleep(5)  # Wait for everything to settle
except Exception as e:
    log_result("4-1_double_start", {"error": str(e)})

#%% Test 4-2: Cancel during autofocus and check /last-af
print("\nTest 4-2: Cancel during autofocus")

try:
    pre_ts = nina_get("/last-af").get('Response', {}).get('Timestamp', '')
    print(f"  Pre-cancel AF timestamp: {pre_ts}")

    nina_get("/auto-focus")
    time.sleep(10)  # Let it run a bit

    cancel_result = nina_get("/auto-focus", cancel=True)
    log_result("4-2a_cancel_response", cancel_result)

    # Wait and check if /last-af updates after cancellation
    time.sleep(3)
    post_cancel_af = nina_get("/last-af")
    post_ts = post_cancel_af.get('Response', {}).get('Timestamp', '')
    log_result("4-2b_last_af_after_cancel", {
        "pre_timestamp": pre_ts,
        "post_timestamp": post_ts,
        "timestamp_changed": pre_ts != post_ts,
        "full_response": post_cancel_af
    })
    # CHECK: Does /last-af update after cancel? (If yes, need to check success field)
    # CHECK: What does CalculatedFocusPoint look like after cancel?

    # Also check /info to see if focuser returns to original position
    time.sleep(5)
    info_after_cancel = nina_get("/info")
    log_result("4-2c_info_after_cancel", info_after_cancel)

except Exception as e:
    log_result("4-2_cancel_test", {"error": str(e)})

#%% Test 4-3: Check /info IsMoving during autofocus (focused poll)
print("\nTest 4-3: IsMoving transitions during autofocus")

try:
    pre_ts = nina_get("/last-af").get('Response', {}).get('Timestamp', '')
    nina_get("/auto-focus")

    transitions = []
    prev_moving = None
    prev_settling = None
    poll_count = 0
    max_polls = 300

    while poll_count < max_polls:
        time.sleep(0.5)  # Faster polling to catch transitions
        info = nina_get("/info")
        resp = info['Response']
        moving = resp['IsMoving']
        settling = resp['IsSettling']
        pos = resp['Position']

        if moving != prev_moving or settling != prev_settling:
            transition = {
                "poll_num": poll_count,
                "time": datetime.now().isoformat(),
                "Position": pos,
                "IsMoving": moving,
                "IsSettling": settling,
                "prev_IsMoving": prev_moving,
                "prev_IsSettling": prev_settling,
            }
            transitions.append(transition)
            print(f"  Transition at poll {poll_count}: "
                  f"moving={prev_moving}->{moving}, "
                  f"settling={prev_settling}->{settling}, "
                  f"pos={pos}")
            prev_moving = moving
            prev_settling = settling

        # Check if AF is done
        curr_ts = nina_get("/last-af").get('Response', {}).get('Timestamp', '')
        if curr_ts != pre_ts and curr_ts != '':
            print(f"  AF completed at poll {poll_count}")
            break

        poll_count += 1

    log_result("4-3_moving_transitions", transitions)
    # CHECK: How many times does IsMoving toggle during autofocus?
    # CHECK: Pattern: does focuser move multiple times (to each measure point)?
    # CHECK: IsSettling behavior?

except Exception as e:
    log_result("4-3_transitions", {"error": str(e)})


#%% ============================================================
# Save all results
# ==============================================================
save_results()
print("\n" + "="*60)
print("ALL TESTS COMPLETE")
print("="*60)
print(f"Results saved to: {LOG_FILE}")
print(f"Total tests run: {len(test_results)}")

# %%
