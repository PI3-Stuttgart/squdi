

cavity_scanner_logic.set_target_position({"a": 8000})
# %%
import time

INITIAL_FREQUENCY = cavity_scanner_logic.scanner_position['a']  # MHz
DRIFT_RATE = -0.01          # MHz per second (Drifting up)
update_interval = .1      # seconds

start_freq_mhz = INITIAL_FREQUENCY
drift_rate_mhz_per_sec = DRIFT_RATE  # MHz per second


current_freq = start_freq_mhz
# We use a monotonous clock for precision timing
start_time = time.monotonic()
print(f"Starting loop at {start_freq_mhz} MHz with drift {drift_rate_mhz_per_sec} MHz/s")

try:
    while True:
        # 1. Calculate elapsed time since start to avoid accumulating sleep errors
        now = time.monotonic()
        elapsed_time = now - start_time
        
        # 2. Calculate the new frequency based on total elapsed time
        # Formula: Frequency = Start + (Rate * Time)
        current_freq = start_freq_mhz + (drift_rate_mhz_per_sec * elapsed_time)
        
        # 3. Apply the logic
        # Using the specific syntax you requested
        print('current_freq:', current_freq)
        cavity_scanner_logic.set_target_position({"a": current_freq})
        
        # 4. Wait for the next update cycle
        time.sleep(update_interval)

except KeyboardInterrupt:
    print("\nLoop stopped by user.")
    print(f"Final Frequency: {current_freq:.6f} MHz")
# %%
