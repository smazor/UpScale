#!/usr/bin/env python3
"""
Upscale an image for glass print output.

What it does:
  - Loads an input image (RGBA or RGB) from the in-image/ folder by default
  - Composites transparency onto a background colour (white by default)
  - Progressively upscales to the target size using LANCZOS
    (multi-pass gives sharper results for large scale factors)
  - Applies print-optimised enhancement: contrast, colour, and resolution-aware
    UnsharpMask output sharpening
  - Preserves the source colour profile (or embeds sRGB) so the lab isn't guessing
  - Saves TIFF (print-lab format) + PNG (preview) to out-image/
  - Packages both into a ZIP alongside them

Configuration:
  Key parameters live in config.xml at the project root. Precedence is:
      command-line flag  >  config.xml  >  built-in fallback
  Pass --config PATH to use a different config file.

Usage (run from the project root, or use scripts/upscale.sh from anywhere):
    # Use everything from config.xml (default input from in-image/, height 100 cm)
    python3 src/upscale.py

    # Pick a specific input (looked up in in-image/ if not a full path)
    python3 src/upscale.py Liane.png

    # Override the print size on the command line
    python3 src/upscale.py Liane.png --height-cm 150
    python3 src/upscale.py Liane.png --long-edge 17700

    # Transparent areas filled with a custom colour instead of white
    python3 src/upscale.py Liane.png --background 0,0,0   # black

Target size (set exactly one; setting several is an error):
    --height-cm   physical height in cm  (default: 100 cm = 1 m)
    --width-cm    physical width in cm
    --long-edge   long edge in pixels    (e.g. 14170 ≈ 120 cm at 300 DPI)
"""

from __future__ import annotations

import argparse
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageFilter, ImageEnhance, ImageOps


# ---------------------------------------------------------------------------
# Paths & defaults
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent   # repository root (script lives in src/)
DEFAULT_CONFIG = PROJECT_ROOT / "config.xml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "out-image"

# Image file extensions recognised when auto-picking from the input folder.
IMG_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}

# Mutually-exclusive ways to specify the target size.
SIZE_KEYS = ("long_edge", "height_cm", "width_cm")

# Built-in fallbacks, used only when neither CLI nor config.xml supplies a value.
DEFAULTS = {
    "input": None,             # filename; None -> auto-pick from input_dir
    "input_dir": "in-image",   # where inputs live (relative to project root)
    "output_dir": None,        # None -> the project's out-image/ folder
    "prefix": None,            # None -> input filename stem
    "background": "255,255,255",
    "long_edge": None,         # px
    "height_cm": 100.0,        # default target: 100 cm (1 m) tall
    "width_cm": None,          # cm
    "dpi": 300,
    "contrast": 1.08,
    "color": 1.03,
    # Output sharpening via UnsharpMask (resolution-aware, print-standard).
    "sharpen_amount": 80.0,    # percent strength; 0 disables sharpening
    "sharpen_radius": 0.0,     # px; 0 -> auto-scale from the enlargement factor
    "sharpen_threshold": 3,    # ignore differences below this (protects flat areas)
    "smooth": False,
    "embed_srgb": True,        # embed an sRGB profile when the source has none
    "max_pixels": 900_000_000,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upscale image for glass print and package as ZIP. "
                    "Defaults come from config.xml; CLI flags override it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # All flag defaults are None so we can tell whether the user set them.
    parser.add_argument(
        "input", nargs="?", default=None,
        help="Input image (default: from config.xml / in-image/ folder). "
             "A bare filename is looked up inside the input folder.",
    )
    parser.add_argument(
        "--config", default=None,
        help=f"Path to XML config file (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--input-dir", default=None,
        help="Folder to look for the input image in (default: in-image)",
    )
    parser.add_argument(
        "--long-edge", type=int, default=None,
        help="Target long edge in pixels (e.g. 14170 ≈ 120 cm at 300 DPI)",
    )
    parser.add_argument(
        "--height-cm", type=float, default=None,
        help="Target physical height in cm (default: 100)",
    )
    parser.add_argument(
        "--width-cm", type=float, default=None,
        help="Target physical width in cm",
    )
    parser.add_argument(
        "--dpi", type=int, default=None,
        help="DPI metadata to embed in output files (default: 300)",
    )
    parser.add_argument(
        "--prefix", default=None,
        help="Output filename prefix (default: input filename stem)",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directory to write outputs into (default: out-image/)",
    )
    parser.add_argument(
        "--background", default=None,
        help="RGB colour to fill transparent areas, e.g. '255,255,255' (white)",
    )
    parser.add_argument("--contrast", type=float, default=None,
                        help="Contrast enhancement factor (default: 1.08)")
    parser.add_argument("--color", type=float, default=None,
                        help="Colour saturation factor (default: 1.03)")
    parser.add_argument("--sharpen-amount", type=float, default=None,
                        help="Output sharpening strength %% (UnsharpMask; default 80, 0 = off)")
    parser.add_argument("--sharpen-radius", type=float, default=None,
                        help="Sharpening radius in px (default 0 = auto from enlargement)")
    parser.add_argument("--sharpen-threshold", type=int, default=None,
                        help="Sharpening threshold; ignores low-contrast areas (default 3)")
    parser.add_argument("--smooth", action="store_true",
                        help="Apply a light smoothing pass to reduce artifacts")
    parser.add_argument("--no-embed-srgb", action="store_true",
                        help="Do not embed an sRGB profile when the source lacks one")
    parser.add_argument("--max-pixels", type=int, default=None,
                        help="Safety cap for total output pixels (default: 900,000,000)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Config file (XML)
# ---------------------------------------------------------------------------

def _to_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"expected true/false, got {raw!r}")


# How each <element> in config.xml is parsed.
CONFIG_SPEC = {
    "input": str,
    "input_dir": str,
    "output_dir": str,
    "prefix": str,
    "background": str,
    "long_edge": int,
    "height_cm": float,
    "width_cm": float,
    "dpi": int,
    "contrast": float,
    "color": float,
    "sharpen_amount": float,
    "sharpen_radius": float,
    "sharpen_threshold": int,
    "smooth": _to_bool,
    "embed_srgb": _to_bool,
    "max_pixels": int,
}


def load_config(path: Optional[Path]) -> dict:
    """Parse config.xml into a dict of typed values. Missing file -> {}."""
    if not path or not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid config XML {path}: {exc}")

    cfg: dict = {}
    for key, convert in CONFIG_SPEC.items():
        el = root.find(key)
        if el is not None and el.text is not None and el.text.strip():
            try:
                cfg[key] = convert(el.text.strip())
            except ValueError as exc:
                raise ValueError(f"Bad value for <{key}> in {path.name}: {exc}")
    return cfg


def resolve_settings(args: argparse.Namespace, config: dict) -> dict:
    """Merge built-in defaults <- config.xml <- command-line flags."""
    settings = dict(DEFAULTS)
    settings.update(config)
    cli = vars(args)

    # Size spec is special: a CLI size flag wins *exclusively* over config,
    # which wins exclusively over the built-in default. We never mix sources.
    cli_size = {k: cli[k] for k in SIZE_KEYS if cli.get(k) is not None}
    cfg_size = {k: config[k] for k in SIZE_KEYS if k in config}
    if cli_size:
        chosen, source = cli_size, "the command line"
    elif cfg_size:
        chosen, source = cfg_size, "config.xml"
    else:
        chosen, source = {"height_cm": DEFAULTS["height_cm"]}, "defaults"
    if len(chosen) > 1:
        raise ValueError(
            f"Only one target size may be set, but {source} sets {len(chosen)}: "
            f"{', '.join(chosen)}. Pick one of height_cm / width_cm / long_edge."
        )
    for k in SIZE_KEYS:
        settings[k] = chosen.get(k)

    # Remaining scalar/string overrides from the command line.
    for k in ("input", "input_dir", "output_dir", "prefix", "background",
              "dpi", "contrast", "color", "sharpen_amount", "sharpen_radius",
              "sharpen_threshold", "max_pixels"):
        if cli.get(k) is not None:
            settings[k] = cli[k]
    if cli.get("smooth"):
        settings["smooth"] = True
    if cli.get("no_embed_srgb"):
        settings["embed_srgb"] = False
    return settings


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def resolve_dir(value: Optional[str], fallback: str) -> Path:
    """Resolve a (possibly relative) directory against CWD, then project root."""
    p = Path(value).expanduser() if value else Path(fallback)
    if not p.is_absolute():
        cwd_candidate = Path.cwd() / p
        p = cwd_candidate if cwd_candidate.exists() else PROJECT_ROOT / p
    return p


def resolve_input(input_val: Optional[str], input_dir: Path) -> Path:
    """Find the input image: explicit path, name inside input_dir, or auto-pick."""
    if input_val:
        p = Path(input_val).expanduser()
        if p.exists():
            return p.resolve()
        candidate = input_dir / p.name
        if candidate.exists():
            return candidate.resolve()
        return p.resolve()  # not found; let validate_input report it clearly

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    images = sorted(
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMG_EXTS
    )
    if not images:
        raise FileNotFoundError(f"No input given and no images found in {input_dir}/")
    if len(images) > 1:
        names = ", ".join(f.name for f in images)
        raise ValueError(
            f"No input given and multiple images in {input_dir}/ ({names}). "
            f"Specify one explicitly or set <input> in config.xml."
        )
    return images[0].resolve()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_background_color(raw: str) -> Tuple[int, int, int]:
    parts = [int(x.strip()) for x in raw.split(",")]
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
        raise ValueError(f"--background must be three 0-255 values, e.g. '255,255,255'. Got: {raw!r}")
    return tuple(parts)  # type: ignore[return-value]


def validate_input(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")


def resolve_target_size(
    in_w: int,
    in_h: int,
    dpi: int,
    long_edge: Optional[int],
    height_cm: Optional[float],
    width_cm: Optional[float],
) -> Tuple[int, int, str]:
    """Compute target pixel dimensions from whichever size spec is set."""
    if in_w <= 0 or in_h <= 0:
        raise ValueError("Invalid input image dimensions.")
    if long_edge is not None:
        scale = long_edge / max(in_w, in_h)
        basis = f"long edge {long_edge} px"
    elif height_cm is not None:
        scale = (height_cm / 2.54 * dpi) / in_h
        basis = f"height {height_cm:g} cm"
    elif width_cm is not None:
        scale = (width_cm / 2.54 * dpi) / in_w
        basis = f"width {width_cm:g} cm"
    else:
        raise ValueError("No target size specified (long_edge / height_cm / width_cm).")
    return max(1, round(in_w * scale)), max(1, round(in_h * scale)), basis


def ensure_safe_pixel_count(width: int, height: int, max_pixels: int) -> None:
    total = width * height
    if total > max_pixels:
        raise ValueError(
            f"Output too large: {width}×{height} = {total:,} px. "
            f"Reduce the target size or increase --max-pixels."
        )


def has_transparency(img: Image.Image) -> bool:
    """True for RGBA / grey+alpha / palette images, incl. palette-index transparency."""
    return img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info


def flatten_alpha(img: Image.Image, bg_color: Tuple[int, int, int]) -> Image.Image:
    """Composite any transparency onto a solid background, returning an RGB image."""
    if has_transparency(img):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, bg_color)
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def icc_is_rgb(profile: bytes) -> bool:
    """True if the ICC profile's data colour space (header bytes 16-20) is RGB."""
    return len(profile) >= 20 and profile[16:20] == b"RGB "


def progressive_upscale(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Upscale in steps of at most 2× per pass.
    A single large LANCZOS jump loses sharpness; iterative 2× passes retain it.
    """
    current = img
    while True:
        cw, ch = current.size
        if cw >= target_w and ch >= target_h:
            break
        step_w = min(cw * 2, target_w)
        step_h = min(ch * 2, target_h)
        current = current.resize((step_w, step_h), Image.Resampling.LANCZOS)
    if current.size != (target_w, target_h):
        current = current.resize((target_w, target_h), Image.Resampling.LANCZOS)
    return current


def auto_sharpen_radius(scale_factor: float) -> float:
    """
    Pick an UnsharpMask radius matched to how far a source pixel was stretched.
    A big enlargement blurs each edge across ~scale_factor px, so the radius must
    grow with it — but it is capped to avoid heavy haloing.
    """
    return min(6.0, max(1.0, scale_factor * 0.6))


def enhance_for_print(
    img: Image.Image,
    contrast: float,
    color: float,
    sharpen_amount: float,
    sharpen_radius: float,
    sharpen_threshold: int,
    smooth: bool,
    scale_factor: float,
) -> Image.Image:
    # Tone/colour first, then a light optional smoothing, then output sharpening
    # last — sharpening is always the final step in a print pipeline.
    out = ImageEnhance.Contrast(img).enhance(contrast)
    out = ImageEnhance.Color(out).enhance(color)
    if smooth:
        out = out.filter(ImageFilter.SMOOTH)
    if sharpen_amount > 0:
        radius = sharpen_radius if sharpen_radius > 0 else auto_sharpen_radius(scale_factor)
        out = out.filter(ImageFilter.UnsharpMask(
            radius=radius, percent=round(sharpen_amount), threshold=sharpen_threshold))
    return out


def load_srgb_profile() -> Optional[bytes]:
    """Return sRGB ICC profile bytes, or None if littlecms is unavailable."""
    try:
        from PIL import ImageCms
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


def save_outputs(
    img: Image.Image,
    out_dir: Path,
    prefix: str,
    dpi: int,
    icc_profile: Optional[bytes],
) -> Tuple[Path, Path]:
    tiff_path = out_dir / f"{prefix}.tiff"
    png_path = out_dir / f"{prefix}.png"
    common = {"dpi": (dpi, dpi)}
    if icc_profile:
        common["icc_profile"] = icc_profile
    img.save(tiff_path, format="TIFF", compression="tiff_lzw", **common)
    img.save(png_path, format="PNG", optimize=True, **common)
    return tiff_path, png_path


def make_zip(zip_path: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fp in files:
            zf.write(fp, arcname=fp.name)


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def physical_size_cm(pixels: int, dpi: int) -> str:
    cm = pixels / dpi * 2.54
    return f"{cm:.1f} cm"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve() if args.config else DEFAULT_CONFIG

    try:
        config = load_config(config_path)
        settings = resolve_settings(args, config)

        input_dir = resolve_dir(settings["input_dir"], "in-image")
        input_path = resolve_input(settings["input"], input_dir)
        out_dir = (
            Path(settings["output_dir"]).expanduser().resolve()
            if settings["output_dir"] else DEFAULT_OUTPUT_DIR
        )

        validate_input(input_path)
        bg_color = parse_background_color(settings["background"])
        prefix = settings["prefix"] or input_path.stem
        dpi = settings["dpi"]
        out_dir.mkdir(parents=True, exist_ok=True)  # only once the inputs check out

        # Increase PIL's pixel limit for large upscales
        Image.MAX_IMAGE_PIXELS = settings["max_pixels"] + 1

        cfg_note = config_path.name if config else "built-in defaults"
        print(f"Config:  {cfg_note}")

        with Image.open(input_path) as raw:
            im = ImageOps.exif_transpose(raw)
            in_w, in_h = im.size
            in_mode = im.mode
            # Capture any embedded colour profile before resize/enhance discard it.
            icc_profile = im.info.get("icc_profile") or raw.info.get("icc_profile")

            target_w, target_h, basis = resolve_target_size(
                in_w, in_h, dpi,
                settings["long_edge"], settings["height_cm"], settings["width_cm"],
            )
            ensure_safe_pixel_count(target_w, target_h, settings["max_pixels"])
            scale_factor = max(target_w / in_w, target_h / in_h)
            effective_ppi = dpi / scale_factor if scale_factor > 0 else dpi

            print(f"Input :  {input_path.name}  ({in_w}×{in_h}, mode={in_mode})")
            print(f"Target:  {basis}")
            print(f"Output:  {target_w}×{target_h}  @ {dpi} DPI  "
                  f"({physical_size_cm(target_w, dpi)} × {physical_size_cm(target_h, dpi)})")
            print(f"Scale :  {scale_factor:.2f}×   (real source detail ≈ {effective_ppi:.0f} PPI)")
            if scale_factor > 4 or effective_ppi < 150:
                print(f"  ⚠ Large enlargement: the source only carries ~{effective_ppi:.0f} PPI of"
                      f" real detail at this size (≥150 PPI is preferable for crisp prints).")
                print( "    Options: lower --dpi (large canvases are viewed from a distance),"
                       " print smaller, or pre-upscale with an AI tool (Real-ESRGAN / Topaz).")
            if has_transparency(im):
                print(f"Alpha :  compositing transparency onto RGB {bg_color}")

            rgb = flatten_alpha(im, bg_color)

        # A grey/CMYK profile no longer describes the RGB data we write.
        if icc_profile and not icc_is_rgb(icc_profile):
            print("Colour:  source profile is not RGB (grey/CMYK) — ignoring it")
            icc_profile = None

        # Colour profile: keep the source's, else embed sRGB so the lab isn't guessing.
        if not icc_profile and settings["embed_srgb"]:
            icc_profile = load_srgb_profile()
            if icc_profile:
                print("Colour:  no source profile — embedding sRGB")
            else:
                print("Colour:  no source profile and littlecms unavailable — none embedded")
        elif icc_profile:
            print("Colour:  preserving embedded source profile")

        upscaled = progressive_upscale(rgb, target_w, target_h)
        final = enhance_for_print(
            upscaled,
            contrast=settings["contrast"],
            color=settings["color"],
            sharpen_amount=settings["sharpen_amount"],
            sharpen_radius=settings["sharpen_radius"],
            sharpen_threshold=settings["sharpen_threshold"],
            smooth=settings["smooth"],
            scale_factor=scale_factor,
        )

        tiff_path, png_path = save_outputs(final, out_dir, prefix, dpi, icc_profile)
        zip_path = out_dir / f"{prefix}_package.zip"
        make_zip(zip_path, [tiff_path, png_path])

        print("\nCreated files:")
        for path in [tiff_path, png_path, zip_path]:
            print(f"  {path.name}  ({human_size(path.stat().st_size)})")

        print("\nDone.")
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
