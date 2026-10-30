# Change log for temptop
# Terminal temperature monitoring program by Scoobin.


## [0.7.0]

### Added
- Additional 5 degree graph markers top and bottom of graph when appropriate (see Changed)

### Changed
- Graph scaling improvements, with 5 degree increments at top/bottom of graph when appropriate. Purpose is to keep graph tight and limit empty space. 
- Remove redundant 10 degree markers from top and bottom of graph when there are no displayed measurements in .

### Fixed
- Text 'PAUSED' is back when paused, which disappeared in last version.


## [0.6.0]

### Added

- Ability to reset individual sensor names instead of having to reset all just to reset one.

### Changed

- Improved graph scaling (more coming).

### Fixed

- Pause program now work. 
- Device order now saves. 

## [0.5.1]

### Added

- Ability to swap order of devices on the main screen (done through Device Manager)

### Changed

- Allowed overlapping dots to alternate their plot lines instead of one just hiding the one behind it. 
- Replaced yellow alarm icons with dark grey (red when alarm is active). 
- Moved alarm icon from end of device line after temps to between device name and current temp so that temps without alarms set stay aligned.
- Made Y-axis (temp) 10 degree guide lines more symmetrical/evenly spaced.
- Changed sensor numbering to column-major (down then across) from row-major (across then down).

### Fixed

- Bug fixed in plotter.py file.

### Removed

- Ticks beside devices removed, since devices are now hidden when unselected to tidy up the main screen.

## [0.4.1]

### Fixed

- Device Manager now works as expected.

## [0.4.0] - 2026-10-08

### Added

- Nvidia temperature monitoring using NVML with fallback to nvidia-smi, so that Nvidia temps are detected on Wayland.
- Option to view 20 minute graph (in addition to existing .5,1,2,3,5,10,15,30,60 minte graphs).

### Changed

- Only extend graph range to 2 degrees above and below highest and lowest displayed temperatures.
- Current temps from light blue to orange, and max temps from dark grey to a more visible dark red.
- Show sensors on first run but do not show any which have been disabled on subsequent runs.
- Initial work to fix broken Device Manager feature.
- correct to new filename reffered to by in-app help (H key).
- program filename to temptop (from temp-top).
- Leave a blank line between temps and program options at bottom of window.
- Minor updates to README file.


### Removed
- Removed word 'LIVE' from near top left corner, as it's unncessary. If the graph is visible then it IS live.


## [0.3.0] - 2026-10-01

### Added

- Temperature markers on both sides of the window for easier temp tracking.

### Changed 

- Hide alarm icons except for any that have been enabled, to reduce clutter.
- Remove minimum (30 degrees) and maximum (100 degrees) from the graph and replace with dynamic range based on what's shown on the screen.
- Only show 5 degrees above and 5 below max and min temps.
- Make the screen refresh no more often than the graph's update rate.

### Fixed
- Fixed corrupted temperature key (table) display.

## [0.2.0]
## [0.1.0] 
- Initial Prototype and Alpha.
