import os
import subprocess

PRESETS = {
    "h264": {
        "vcodec": "libx264",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "extension": ".mp4"
    },
    "mp4": {
        "vcodec": "libx264",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "extension": ".mp4"
    },
    "webm": {
        "vcodec": "libvpx-vp9",
        "acodec": "libvorbis",
        "pix_fmt": "yuv420p",
        "extension": ".webm"
    },
    "vp9": {
        "vcodec": "libvpx-vp9",
        "acodec": "libvorbis",
        "pix_fmt": "yuv420p",
        "extension": ".webm"
    },
    "h265": {
        "vcodec": "libx265",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "extension": ".mp4"
    },
    "hevc": {
        "vcodec": "libx265",
        "acodec": "aac",
        "pix_fmt": "yuv420p",
        "extension": ".mp4"
    }
}

def videoFormatChanger(
    input_path: str,
    formats: list | str | dict | None = None,
    overwrite_input: bool = True
) -> dict[str, str]:
    """
    Transcodes a video to one or more formats using FFmpeg.
    
    Args:
        input_path: Path to the source video file.
        formats: A single preset name/string, a dict with custom settings,
                 or a list of these. If None, defaults to 'h264'.
        overwrite_input: If True, only one format is requested, and its extension matches
                         the input_path, the original input video is replaced.
                         
    Returns:
        A dictionary mapping the format specification name (or index) to the generated file path.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video file not found: {input_path}")
        
    if formats is None:
        formats = ["h264"]
    elif not isinstance(formats, list):
        formats = [formats]
        
    results = {}
    
    for idx, fmt in enumerate(formats):
        config = {}
        preset_name = f"format_{idx}"
        
        if isinstance(fmt, str):
            preset_name = fmt
            if fmt.lower() in PRESETS:
                config = PRESETS[fmt.lower()].copy()
            else:
                ext = fmt if fmt.startswith(".") else f".{fmt}"
                if ext == ".webm":
                    config = PRESETS["webm"].copy()
                elif ext == ".mp4":
                    config = PRESETS["h264"].copy()
                else:
                    config = {
                        "vcodec": "copy",
                        "acodec": "copy",
                        "extension": ext
                    }
        elif isinstance(fmt, dict):
            config = fmt.copy()
            preset_name = config.get("name", f"format_{idx}")
        else:
            print(f"Unsupported format type: {type(fmt)}")
            continue
            
        vcodec = config.get("vcodec", "libx264")
        acodec = config.get("acodec", "aac")
        pix_fmt = config.get("pix_fmt", "yuv420p")
        ext = config.get("extension", ".mp4")
        if not ext.startswith("."):
            ext = f".{ext}"
            
        custom_output_path = config.get("output_path")
        should_overwrite = config.get("overwrite_input", overwrite_input)
        
        is_single_overwrite = (
            len(formats) == 1 and 
            should_overwrite and 
            custom_output_path is None and 
            os.path.splitext(input_path)[1].lower() == ext.lower()
        )
        
        if custom_output_path:
            out_path = custom_output_path
        elif is_single_overwrite:
            base_dir = os.path.dirname(input_path)
            base_name = os.path.basename(input_path)
            temp_name = f"temp_{os.path.splitext(base_name)[0]}{ext}"
            out_path = os.path.join(base_dir, temp_name)
        else:
            base, _ = os.path.splitext(input_path)
            out_path = f"{base}_{preset_name}{ext}"
            
        cmd = ["ffmpeg", "-i", input_path]
        
        if vcodec:
            cmd.extend(["-vcodec", vcodec])
        if pix_fmt:
            cmd.extend(["-pix_fmt", pix_fmt])
        if acodec:
            cmd.extend(["-acodec", acodec])
            
        cmd.extend(["-y", out_path])
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if is_single_overwrite:
                if os.path.exists(out_path):
                    os.replace(out_path, input_path)
                    results[preset_name] = input_path
                else:
                    results[preset_name] = input_path
            else:
                results[preset_name] = out_path
        except Exception as e:
            print(f"FFmpeg transcoding failed for preset '{preset_name}': {e}")
            if is_single_overwrite:
                results[preset_name] = input_path
            else:
                results[preset_name] = input_path
                
    return results
