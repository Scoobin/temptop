# Change log for temptop
# Terminal temperature monitoring program by Scoobin.


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
