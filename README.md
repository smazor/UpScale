# UpScale

This project contains an image upscaling script for glass print output.

## Setup

Create and activate the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Project layout

- `src/upscale.py` — the upscaling program
- `scripts/upscale.sh` — launcher that uses the project's `.venv`, so it works
  from any directory (`scripts/upscale.sh Liane.png --height-cm 80`)
- `config.xml` — default parameters (edit this instead of typing flags)
- `in-image/` — put source images here (default input location); subfolders
  such as `in-image/sagi/` are fine, see "Working with subfolders" below
- `out-image/` — generated TIFF / PNG / ZIP outputs, usually one subfolder per
  batch (`run2/`, `New-Art/`, `sagi/`, ...)

## Configuration

Default parameters live in `config.xml`. Precedence is:

```
command-line flag  >  config.xml  >  built-in fallback
```

By default the script reads `Liane.png` from `in-image/` and produces a print
**100 cm (1 m) tall** at 300 DPI. Edit `config.xml` to change the default
input, size, DPI, background, or enhancement settings. Use a different config
file with `--config path/to/file.xml`.

## Usage

Run from the repository root, or call `scripts/upscale.sh` from anywhere (it
takes the same arguments and picks up the `.venv` automatically). With no
arguments it uses everything in `config.xml`:

```bash
python3 src/upscale.py
```

Override the input (a bare filename is looked up inside `in-image/`):

```bash
python3 src/upscale.py Shai.png
```

### Target size (set exactly one)

- `--height-cm`: target physical height in cm (config default: `100`)
- `--width-cm`: target physical width in cm
- `--long-edge`: target long edge in pixels (e.g. `14170` ≈ 120 cm at 300 DPI)

Setting more than one size, on the command line or in `config.xml`, is an
error rather than a silent pick. A size flag on the command line replaces the
size in `config.xml` entirely (the two are never mixed). The other dimension
follows the image's aspect ratio, so a portrait image fixed at 150 cm wide will
be taller than 150 cm.

### Other common options

- `--config`: path to an alternate XML config file
- `--input-dir`: folder to look for the input image (default: `in-image`)
- `--dpi`: DPI metadata for output files (default: `300`)
- `--prefix`: output file prefix (default: input filename stem)
- `--output-dir`: output folder (default: `out-image/`)
- `--background`: RGB fill for transparency, e.g. `0,0,0`
- `--contrast`: contrast multiplier (default: `1.08`)
- `--color`: color saturation multiplier (default: `1.03`)
- `--sharpen-amount`: output sharpening strength %, UnsharpMask (default: `80`, `0` = off)
- `--sharpen-radius`: sharpening radius in px (default: `0` = auto from enlargement)
- `--sharpen-threshold`: protect low-contrast areas (default: `3`)
- `--smooth`: add a light smoothing pass
- `--no-embed-srgb`: don't embed sRGB when the source lacks a colour profile

### Resolution & colour notes

- The script preserves the source ICC colour profile (or embeds sRGB) so the
  print lab doesn't have to guess your colour space. A grey or CMYK source
  profile is not carried over, because it would not describe the RGB output;
  sRGB is embedded instead.
- Transparency is composited onto `--background` for every kind of transparent
  PNG: RGBA, grey+alpha, and palette images with transparency.
- It reports the **effective PPI** (real detail) and warns on large
  enlargements. A 100 cm print at 300 DPI from a ~1000 px source is a ~12×
  enlargement (~24 PPI of real detail). For crisper results, lower `--dpi`
  (large canvases are viewed from a distance), print smaller, or pre-upscale
  the source with an AI tool (Real-ESRGAN / Topaz) before running this script.

### Example

```bash
python3 src/upscale.py Liane.png --height-cm 150 --background 0,0,0
```

### Working with subfolders

A bare filename is looked up in `--input-dir`, so a batch kept in a subfolder
is run like this, with each image given its own size and the results sent to a
matching output folder:

```bash
python3 src/upscale.py woman.png --input-dir in-image/New-Art --width-cm 150 --output-dir out-image/New-Art
python3 src/upscale.py house.png --input-dir in-image/New-Art --height-cm 60  --output-dir out-image/New-Art
```

If you give no input at all, the script auto-picks the image in the input
folder, but only when there is exactly one.

## Outputs

The script saves into `out-image/`:

- `<prefix>.tiff`
- `<prefix>.png`
- `<prefix>_package.zip`

## Version control

The repository tracks the code, configuration and docs only. The contents of
`in-image/` (source artwork) and `out-image/` (multi-gigabyte print files) are
git-ignored; the folders themselves are kept with a `.gitkeep`. Back the images
up separately.

## Notes

The virtual environment is stored in `.venv/`.
