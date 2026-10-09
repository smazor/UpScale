# Hanurit House – Glass Print Upscale Project

## Project overview

Prepare artwork for large-format glass print production.
Source files: `in-image/` (e.g. `Liane.png` — 1074×944 px, RGBA).
Script:       `src/upscale.py` (launcher: `scripts/upscale.sh`, works from any directory)
Config:       `config.xml` (project root — default parameters)
Outputs:      `out-image/` — TIFF (print-lab), PNG (preview), ZIP (package)

---

## Quick start

```bash
# Use everything from config.xml (input Liane.png, 100 cm / 1 m tall at 300 DPI)
python3 src/upscale.py

# Pick a specific input (a bare name is looked up inside in-image/)
python3 src/upscale.py Shai.png

# Override the print size on the command line
python3 src/upscale.py Liane.png --height-cm 150
python3 src/upscale.py Liane.png --long-edge 17700

# Custom background for transparent areas (default: white)
python3 src/upscale.py Liane.png --background 0,0,0
```

---

## Configuration (config.xml)

Default parameters live in `config.xml` at the project root. Precedence is:

```
command-line flag  >  config.xml  >  built-in fallback
```

Set the target size with exactly one of `<height_cm>` (default `100`),
`<width_cm>`, or `<long_edge>`. Setting more than one (CLI or config) is an error.
A CLI size flag replaces the config size entirely. Use a different config file with
`--config path.xml`.

Batches in subfolders: pass `--input-dir in-image/<folder>` with a bare filename, and
`--output-dir out-image/<folder>` to keep results grouped.

## Version control

Git tracks code, config and docs only. `in-image/` and `out-image/` contents are
git-ignored (source artwork and multi-GB print files); only `.gitkeep` files are kept.
There is no remote configured yet, so nothing is pushed.

## Common size values at 300 DPI

| Physical size | Flag                          |
|---------------|-------------------------------|
| 100 cm tall   | `--height-cm 100` (default)   |
| 150 cm tall   | `--height-cm 150`             |
| 120 cm long   | `--long-edge 14170`           |
| 150 cm long   | `--long-edge 17700`           |

---

## What the script does

1. Composites any transparency (RGBA, grey+alpha, palette) onto a solid background (white by default).
2. Progressively upscales in 2× passes using LANCZOS — much sharper than a single large jump.
3. Applies print-optimised enhancement: contrast (1.08×), colour (1.03×), and a
   resolution-aware UnsharpMask output-sharpening pass (last).
4. Preserves the source ICC colour profile, or embeds sRGB if none is present
   (a non-RGB grey/CMYK profile is dropped and sRGB is embedded instead).
5. Reports the effective PPI and warns on large enlargements.
6. Saves `{prefix}.tiff` (LZW-compressed, for print labs) and `{prefix}.png` (preview).
7. Packages both into `{prefix}_package.zip`.

---

## Key flags

| Flag            | Default (config) | Description                              |
|-----------------|------------------|------------------------------------------|
| `--height-cm`   | `100`            | Target physical height in cm             |
| `--width-cm`    | —                | Target physical width in cm              |
| `--long-edge`   | —                | Target long edge in pixels               |
| `--config`      | `config.xml`     | Path to the XML config file              |
| `--input-dir`   | `in-image`       | Folder to look for the input image       |
| `--dpi`         | `300`            | DPI metadata embedded in output files    |
| `--prefix`      | input file stem  | Output filename prefix (e.g. `Liane`)    |
| `--output-dir`  | `out-image/`     | Where to write the output files          |
| `--background`  | `255,255,255`    | RGB fill for transparent areas           |
| `--contrast`    | `1.08`           | Contrast enhancement multiplier          |
| `--color`       | `1.03`           | Colour saturation multiplier             |
| `--sharpen-amount`    | `80`       | Output sharpening strength % (0 = off)   |
| `--sharpen-radius`    | `0` (auto) | Sharpening radius in px                   |
| `--sharpen-threshold` | `3`        | Protects low-contrast / flat areas       |
| `--smooth`      | off              | Add a light smoothing pass               |
| `--no-embed-srgb` | off            | Skip embedding sRGB when source has none |

---

## Dependencies

```bash
pip3 install Pillow
```

---

## Notes for print on glass

- Send the `.tiff` file to the print lab; it is uncompressed-friendly (LZW) and DPI-tagged.
- If the print lab requires a specific colour profile (e.g. sRGB ICC), convert in Photoshop or GIMP after upscaling.
- If the glass has a coloured substrate, adjust `--background` to match before printing.
- For prints larger than ~200 cm, consider AI upscaling tools (Real-ESRGAN, Topaz Gigapixel) for even sharper results before running this script.
