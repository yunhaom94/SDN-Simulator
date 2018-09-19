"""
Timeout

1. Timeout is meaningless when under 10ms, thus only consider timeout beyond 10ms. Same for large timeout.
2. Reasonable range is from 10ms to 10s.
3. Since using log axis, should sample small timeouts intensively, but with sparse large timeouts:
    1. 10ms to 100ms; every 10ms
    2. 110ms to 290ms; every 20ms
    3. 310ms to 670ms; every 40ms
    4. 710ms to 1430ms; every 80ms
    5. 1510ms to 2950ms; every 160ms
    6. 3110ms to 5990ms; every 320ms

Multiplier (Maximum multiplier should less than 10s)
    1: 1 to 100 every 10
    2: 1 to 40 every 4
    3: 1 to 20 every 2
    4: 1 to 10 every 1
    5: 1 to 4 every 0.4
    6: 1 to 2 every 0.2

Cache size: TBD

Threshold:
    2 to 5 every 1
"""

import os
import argparse

if __name__ == '__main__':
    # Location of tracefile:
    trace_path = input("tracefile path: ")
    start_id = int(input("start switch id (inclusive): "))

    # Num of switches per file
    x = 10

    # Generate timeout list mentioned above
    timeout_list = []
    start = 10
    for i in range(6):
        cur_range = []
        for j in range(10):
            cur_range.append(start)
            start = start + 10 * (2 ** i)
        timeout_list.append(cur_range)

    # Generate no_cache test files
    num_file = 60 // x
    for i in range(num_file):
        file_name = "no_cache_config" + str(i) + ".txt"
        cur_fp  = open(file_name, "w+")

        cur_fp.write("[COMMON]\n")
        cur_fp.write("trace_path=" + trace_path + "\n")
        cur_fp.write("num_switches=" + str(x) + "\n")

        for j in range(x):
            cur_fp.write("[SW" + str(start_id) + "]\n")
            start_id += 1

            # Detect timeout:
            total_index = i * x + j
            row = total_index // 10
            col = total_index % 10
            cur_fp.write("timeout=" + str(timeout_list[row][col]) + "\n")
    
        cur_fp.close()

            





    





