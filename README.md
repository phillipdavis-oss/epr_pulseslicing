PyQt6 GUI for controlling FEL-ESR lasers. There are two types of lasers (Viron, CNI) that have different communication protocols (telnet, RS-232). The GUI is designed to have asynchronous threads that run the callbacks in parallel with the main GUI loop. This is initiated with the

```
self.loop = asyncio.new_event_loop()
asyncio.set_event_loop(self.loop)
```

code block. The `async` functions then run in that threaded loop.

The software will initialize communication with the laser, allow a user to set triggering mode, laser power, and begin firing. It will also send the timings to a connected DG645 that drives the external triggers and sets the pulse timings.

The GUI was built with `pyqt6-tools designer`, which is for making GUI front ends. Use it to modify the laser_timing.ui file and then

```
pyuic6 -o laser_timing.py laser_timing.ui
```

to convert it to a python file that can be imported in your GUI class file.
