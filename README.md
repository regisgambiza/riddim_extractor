# Riddim Extractor

A GUI tool for organizing riddim music collections by year using audio metadata (ID3 tags).

## Overview

Riddim Extractor is a Windows GUI application designed for reggae/dancehall music collectors who organize their libraries by "riddims" (instrumental backing tracks). It automatically extracts ZIP archives, reads audio metadata (ID3 tags), and organizes folders into year-based subdirectories.

## Features

- Extracts ZIP archives containing riddim collections
- Reads year from audio metadata (TDRC, TORY, date, iTunes tags)
- Organizes folders into `destination/YYYY/FolderName` structure
- Copy or Move modes (configurable in Settings)
- Real-time execution trace with step-by-step logging
- Progress monitoring for batch operations
- Success/Failed lists with detailed error reporting
- Retry failed items with one click
- Dark/Light modern IDM-inspired theme
- System tray support for background operation
- Persistent state tracking (remembers processed folders)

## GUI Overview

```
+------------------------------------------------------------+
|  RIDDIM EXTRACTOR                                          |
|  Source: [C:\...] [Browse...]  Dest: [C:\...] [Browse]     |
|  [Mode: COPY]                                              |
|  +------------------------------------------------------+  |
|  | SOURCE FOLDERS             | PROCESSING LOG       |  |
|  | +------------------------------+  | +--------------+  |  |
|  | [x] 10 LONG Riddim          |  | [14:32:15]   |  |  |
|  | [ ] 12 Gauge Riddim CD      |  | [INFO] Start |  |  |
|  | [x] 3 Star Riddim           |  | [TRACE] Ext. |  |  |
|  | [ ] 40 Calibur Riddim...    |  | [TRACE] Copy |  |  |
|  +-----------------------------+  +----------------+  |  |
|  +------------------------------------------------------+  |
|  [Process Selected]  [Process All]  [Retry Failed]  [Clear]|
|  Progress: [##########--------]  45%                        |
|  Status: Processing: 10 LONG Riddim                        |
+------------------------------------------------------------+
```

## Processing Log

Color-coded trace output with each step on its own line:

```
[14:32:15] [INFO]  Starting folder processing: 10 LONG Riddim
[14:32:16] [TRACE] Found single folder: 10 LONG Riddim
[14:32:16] [TRACE] Copied to: C:\Dest\2009\10 LONG Riddim
[14:32:17] [TRACE] Organized to year path: 2009/10 LONG Riddim
[14:32:17] [TRACE] Found 12 audio files
```

## Workflow

1. Set SOURCE directory (where your riddim folders/ZIPs are)
2. Set DESTINATION directory (where organized folders go)
3. Click "Process All" or select folders and click "Process Selected"
4. Watch real-time trace in the log panel
5. Check destination - folders organized as: `Dest\2009\FolderName\`
6. Any failures appear in Failed list - click "Retry Failed" to retry

## Installation

```bash
# Install Python 3.10+ from python.org
# Clone or download this repository
cd riddim_extractor
pip install -r requirements.txt
python riddim_extractor_gui.py
```

## Requirements

- Python 3.10+
- PySide6 (Qt6 GUI framework)
- mutagen (audio metadata reading)

## Usage Example

**Before:**
```
Source\10 LONG Riddim\
Source\12 Gauge Riddim CD (2OO7)\
Source\3 Star Riddim.zip
```

**After (Copy mode):**
```
Organized\2009\10 LONG Riddim\
Organized\2007\12 Gauge Riddim CD (2OO7)\
Organized\2008\3 Star Riddim\
```

Original source folders unchanged in Copy mode.

## Technical Details

- Uses QThread + QObject worker pattern for non-blocking GUI
- Worker signals: `started`, `progress`, `finished`, `error`, `completed`
- State persisted to JSON (processed/failed folders)
- Audio metadata read via `mutagen.MutagenFile`
- Supported formats: MP3, FLAC, M4A, OGG, WMA, AAC, WAV, AIFF
- Year tags checked: TDRC, TORY, date, iTunes copyright tag
- Thread-safe signal/slot communication

## Troubleshooting

**Q: GUI freezes during processing?**
A: Fixed in v2.0 - worker now runs in proper background thread.

**Q: Folders appear at destination root instead of year subfolder?**
A: Fixed - now copies directly to `Dest\YYYY\FolderName\`

**Q: Log shows long concatenated lines?**
A: Fixed - each trace step now on separate line.

**Q: "QSystemTrayIcon::setVisible: No Icon set" warning?**
A: Harmless - tray icon optional, set in Settings if desired.

## Version History

- **v2.1** - Fixed QCheckBox import, cleaned warnings
- **v2.0** - Major threading fix, direct year organization, trace formatting fix
- **v1.x** - Initial versions