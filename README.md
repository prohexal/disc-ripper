# Disc Ripper - AV1 Encoder

A GUI application for ripping Blu-ray/DVD discs using MakeMKV and encoding them to AV1 format with customizable options.

## Features

- 🎬 **Disc Detection**: Automatically scan and detect inserted discs
- 📊 **Title Selection**: View all available titles with duration, size, and chapter information
- 🎨 **Resolution Control**: Choose from Original, 4K, 1080p, 720p, or 480p
- 🔊 **Audio Track Selection**: Select which audio tracks to include
- 🎧 **High-Quality Audio**: Automatically preserves DTS, DTS-HD, Dolby TrueHD, Dolby Digital (AC3/EAC3)
- 🌈 **HDR Preservation**: Detects and preserves HDR10 metadata during encoding
- 💎 **Dolby Vision Support**: Automatically copies video stream when Dolby Vision is detected
- 🗣️ **Subtitle Selection**: Choose specific subtitle languages to include
- 📑 **Chapter Support**: Option to include or exclude chapter markers
- 🚀 **AV1 Encoding**: High-efficiency AV1 video codec with SVT-AV1 encoder
- 📝 **Real-time Progress**: Live progress tracking and detailed logging
- 🖥️ **Detached Mode**: Runs independently from terminal

## Requirements

### macOS
- Python 3.11 or later
- MakeMKV (auto-installer provided)
- FFmpeg with AV1 support (install via Homebrew)
- Homebrew (recommended for installing FFmpeg and Python)
- TMDb API key (optional, for metadata and cover art)

## Installation

### 1. Install MakeMKV

The application will prompt you to download and install MakeMKV automatically on first run if it's not detected.

Alternatively, you can manually download and install MakeMKV from: https://www.makemkv.com/download/

After installation, the command-line tool should be available at:
```
/Applications/MakeMKV.app/Contents/MacOS/makemkvcon
```

You can verify installation from the Settings menu in the application.

### 2. Install FFmpeg with AV1 Support

Using Homebrew (recommended):
```bash
brew install ffmpeg
```

This will install FFmpeg with SVT-AV1 encoder support.

### 3. Set Up TMDb API (Optional)

For automatic movie metadata and cover art:

1. Go to https://www.themoviedb.org/ and create a free account
2. Visit https://www.themoviedb.org/settings/api to get your API key
3. In the application, go to Settings → TMDb API Key
4. Enter your API key (it's stored securely in your macOS keychain)

The API key is **optional** but enables:
- Automatic movie name lookup
- High-quality cover art download
- Proper metadata tagging

### 4. Verify Installation

Check that both tools are available:
```bash
# Check MakeMKV
/Applications/MakeMKV.app/Contents/MacOS/makemkvcon --version

# Check FFmpeg
ffmpeg -version | grep svt-av1
```

Or use Settings → Check for MakeMKV in the application.

## Usage

### Running the Application

**Quick launch from anywhere:**
```bash
disc-ripper
```

This opens the application detached from the terminal.

**Or run directly from project directory:**
```bash
cd ~/codeRepo/disc-ripper
./launch.sh
```

**Or run attached to terminal (for debugging):**
```bash
/opt/homebrew/bin/python3.11 ~/codeRepo/disc-ripper/disc_ripper.py
```

### Workflow

1. **Insert Disc**: Insert a Blu-ray or DVD disc into your drive

2. **Scan Disc** (Tab 1):
   - Click "Scan for Disc" to detect the inserted disc
   - The application will list all available titles
   - Select the main feature title (usually the longest one)
   - Click "Select Title & Continue"

3. **Configure Encoding** (Tab 2):
   - Click "Auto-Search TMDb" to find movie metadata (requires TMDb API key)
   - Or manually enter the movie name
   - Choose output folder (default: ~/Movies/Ripped)
   - Select video encoding mode (Auto/Copy/AV1)
   - Select desired resolution
   - Select audio tracks to include (multi-select with Cmd/Ctrl)
   - Select subtitle languages to include (multi-select with Cmd/Ctrl)
   - Enable/disable chapter markers
   - Click "Start Encoding"

4. **Monitor Progress** (Tab 3):
   - Watch real-time progress of ripping and encoding
   - View detailed logs of the process
   - Get notification when complete

### Output

The final file will be saved as:
```
~/Movies/Ripped/<movie-name>.mkv
```

With:
- **Video**: AV1 (SVT-AV1) or copy if Dolby Vision detected
- **Audio**: Original codec preserved if DTS/TrueHD/AC3/EAC3, otherwise Opus (128 kbps)
- **Subtitles**: Selected languages copied as-is
- **HDR/DV**: Metadata automatically preserved
- **Container**: MKV format
- **Chapters**: Optional chapter markers

## Configuration

### Encoding Behavior

The application intelligently handles encoding based on source content:

**Video:**
- **Dolby Vision**: Automatically copies video stream (no re-encoding) to preserve DV metadata
- **HDR10/HDR10+**: Encodes to AV1 while preserving color primaries, transfer characteristics, and mastering display metadata
- **SDR**: Standard AV1 encoding with preset 6, CRF 30

**Audio:**
- **High-Quality Formats**: DTS, DTS-HD, Dolby TrueHD, Dolby Digital (AC3/EAC3) are copied without re-encoding
- **Standard Audio**: Other formats converted to Opus @ 128 kbps

**Subtitles:**
- All selected subtitle tracks are copied without modification

### MakeMKV Drive Selection

If you have multiple drives, change the drive number in Tab 1 (default is 0).

## Troubleshooting

### "MakeMKV not found"
- Ensure MakeMKV is installed in `/Applications/`
- Check that the command line tool exists at the expected path

### "FFmpeg not found"
- Install FFmpeg using: `brew install ffmpeg`
- Verify installation: `which ffmpeg`

### "No disc inserted" error
- Ensure disc is fully inserted and recognized by macOS
- Try incrementing the drive number (1, 2, etc.)
- Check Disk Utility to see if the disc is mounted

### Slow encoding
- AV1 encoding is computationally intensive
- Lower resolution or increase CRF value for faster encoding
- Use a faster preset (5, 4) at the cost of file size

### Audio/Video sync issues
- Ensure you're using the latest version of FFmpeg
- Try re-ripping with MakeMKV

## Advanced Usage

### Command Line Options

You can modify the encoding parameters by editing `disc_ripper.py`:

```python
# Line 384 - Video encoding settings
cmd.extend(["-c:v", "libsvtav1", "-preset", "6", "-crf", "30"])
```

**Preset values** (0-13):
- 0-3: Highest quality, slowest
- 4-6: Balanced (default: 6)
- 7-9: Faster, larger files
- 10-13: Fastest, largest files

**CRF values** (0-63):
- 0: Lossless (huge files)
- 20-28: Very high quality
- 30-35: Good quality (default: 30)
- 36-51: Lower quality, smaller files

### Audio Codec Options

To use AAC instead of Opus:
```python
# Replace line 392
cmd.extend(["-c:a", "aac", "-b:a", "192k"])
```

## License

MIT License - feel free to modify and distribute

## Security

The application stores your TMDb API key securely using macOS Keychain. The key is never stored in plain text on disk.

## Contributing

Contributions welcome! Areas for improvement:
- Batch processing multiple discs
- Quality presets (Fast/Balanced/Quality)
- Hardware acceleration support (VideoToolbox on macOS)
- TV show detection and metadata
- Multiple audio/subtitle language profiles

## Credits

- [MakeMKV](https://www.makemkv.com/) - Disc ripping
- [FFmpeg](https://ffmpeg.org/) - Video encoding
- [SVT-AV1](https://gitlab.com/AOMediaCodec/SVT-AV1) - AV1 encoder
