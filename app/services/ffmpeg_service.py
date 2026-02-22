import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional


class FFmpegService:
    """Service for video processing using FFmpeg"""
    
    @staticmethod
    def check_ffmpeg_installed() -> bool:
        """Check if ffmpeg is installed and accessible"""
        try:
            subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    @staticmethod
    def get_video_info(video_path: str) -> Dict:
        """
        Get detailed video metadata using ffprobe
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Dictionary containing video metadata
            
        Raises:
            subprocess.CalledProcessError: If ffprobe fails
        """
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            video_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        return json.loads(result.stdout)
    
    @staticmethod
    def get_duration(video_path: str) -> float:
        """
        Get video duration in seconds
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Duration in seconds as float
        """
        info = FFmpegService.get_video_info(video_path)
        return float(info['format']['duration'])
    
    @staticmethod
    def calculate_crop_dimensions(orig_width: int, orig_height: int, aspect_ratio: str) -> tuple:
        """Return (target_width, target_height) for a given aspect ratio string like '16:9'."""
        aspect_w, aspect_h = map(int, aspect_ratio.split(":"))
        target_aspect = aspect_w / aspect_h
        orig_aspect = orig_width / orig_height
        if orig_aspect > target_aspect:
            new_height = orig_height
            new_width = int(orig_height * target_aspect)
        else:
            new_width = orig_width
            new_height = int(orig_width / target_aspect)
        # Ensure even dimensions (required by most codecs)
        return new_width - (new_width % 2), new_height - (new_height % 2)

    @staticmethod
    def build_crop_filter(orig_w: int, orig_h: int, target_w: int, target_h: int, position: str = "center") -> str:
        """Return ffmpeg crop filter string: crop=w:h:x:y"""
        if position == "top":
            x, y = (orig_w - target_w) // 2, 0
        elif position == "bottom":
            x, y = (orig_w - target_w) // 2, orig_h - target_h
        elif position == "left":
            x, y = 0, (orig_h - target_h) // 2
        elif position == "right":
            x, y = orig_w - target_w, (orig_h - target_h) // 2
        else:  # center
            x, y = (orig_w - target_w) // 2, (orig_h - target_h) // 2
        return f"crop={target_w}:{target_h}:{x}:{y}"

    @staticmethod
    def split_video(
        input_path: str,
        output_dir: Path,
        segment_duration: int,
        aspect_ratio: Optional[str] = None,
        crop_position: str = "center",
        custom_width: Optional[int] = None,
        custom_height: Optional[int] = None,
    ) -> List[Path]:
        """
        Split video into equal-length segments, with optional cropping.

        Uses stream copy (fast, no quality loss) when no crop is needed.
        Re-encodes with libx264 only when a crop filter is applied.
        """
        output_pattern = str(output_dir / "segment_%03d.mp4")

        crop_filter = None
        if aspect_ratio and aspect_ratio != "custom":
            orig_w, orig_h = FFmpegService.get_video_resolution(input_path)
            if orig_w and orig_h:
                target_w, target_h = FFmpegService.calculate_crop_dimensions(orig_w, orig_h, aspect_ratio)
                if target_w != orig_w or target_h != orig_h:
                    crop_filter = FFmpegService.build_crop_filter(orig_w, orig_h, target_w, target_h, crop_position)
        elif aspect_ratio == "custom" and custom_width and custom_height:
            orig_w, orig_h = FFmpegService.get_video_resolution(input_path)
            if orig_w and orig_h:
                tw = custom_width - (custom_width % 2)
                th = custom_height - (custom_height % 2)
                crop_filter = FFmpegService.build_crop_filter(orig_w, orig_h, tw, th, crop_position)

        if crop_filter:
            cmd = [
                'ffmpeg', '-i', input_path,
                '-vf', crop_filter,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                '-c:a', 'copy',
                '-map', '0:v:0', '-map', '0:a?',
                '-segment_time', str(segment_duration),
                '-f', 'segment', '-reset_timestamps', '1',
                output_pattern,
            ]
        else:
            cmd = [
                'ffmpeg', '-i', input_path,
                '-c', 'copy', '-map', '0',
                '-segment_time', str(segment_duration),
                '-f', 'segment', '-reset_timestamps', '1',
                output_pattern,
            ]

        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return sorted(output_dir.glob("segment_*.mp4"))
    
    @staticmethod
    def get_video_resolution(video_path: str) -> tuple:
        """
        Return the display (width, height), accounting for rotation metadata.

        iPhones store videos in sensor orientation (e.g. 1920×1080) and embed
        a rotation tag (90° or 270°) so players rotate on playback. FFmpeg's
        filter graph applies this rotation before any -vf filters, so crop
        math must use the *display* dimensions, not the coded ones.
        """
        info = FFmpegService.get_video_info(video_path)

        for stream in info['streams']:
            if stream['codec_type'] == 'video':
                w = stream['width']
                h = stream['height']

                # 1) Check the 'rotate' metadata tag (MOV/MP4, common on iPhone)
                rotation = 0
                tags = stream.get('tags', {}) or {}
                try:
                    rotation = abs(int(tags.get('rotate', 0)))
                except (ValueError, TypeError):
                    rotation = 0

                # 2) Fall back to Display Matrix side data (newer Apple devices)
                if rotation == 0:
                    for sd in stream.get('side_data_list', []):
                        if sd.get('side_data_type') == 'Display Matrix':
                            try:
                                rotation = abs(int(sd.get('rotation', 0))) % 360
                            except (ValueError, TypeError):
                                pass
                            break

                # Swap dimensions for 90° / 270° rotations
                if rotation in (90, 270):
                    return (h, w)
                return (w, h)

        return (0, 0)