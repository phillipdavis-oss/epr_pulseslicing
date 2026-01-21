from spinapi import *

# Enable the log file
pb_set_debug(1)

pb_select_board(0)

if pb_init() != 0:
	print("Error initializing board: %s" % pb_get_error())
	input("Please press a key to continue.")
	exit(-1)

# Configure the core clock
pb_core_clock(500)

# Program the pulse program
pb_start_programming(PULSE_PROGRAM)
# start = pb_inst_pbonly(0x1, Inst.LOOP, 50, 250.0 * ms)
# pb_inst_pbonly(0x3, Inst.CONTINUE, 0, 250.0 * ms)
# pb_inst_pbonly(0x2, Inst.CONTINUE, 0, 250.0 * ms)
# pb_inst_pbonly(0x0, Inst.END_LOOP, start, 250.0 * ms)
# pb_inst_pbonly(0x0, Inst.STOP, 0, 1.0 * ms)
len = 50 * ns
start = pb_inst_pbonly(0x0, Inst.WAIT, 0, 20 * ns)
# pb_inst_pbonly(0x3, Inst.CONTINUE, 0, 8 * ns)
pb_inst_pbonly(0b001000000000000000000001, Inst.CONTINUE, 0, 10 * ns)
pb_inst_pbonly(0b001000000000000000000010, Inst.CONTINUE, 0, 10 * ns)
pb_inst_pbonly(0x000000, Inst.BRANCH, 0, 1 * ms)
pb_stop_programming()

# Trigger the board
pb_reset() 
pb_start()

print("Continuing will stop program execution\n");
input("Please press a key to continue.")

pb_stop()
pb_close()