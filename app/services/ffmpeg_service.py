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
    def split_video(
        input_path: str,
        output_dir: Path,
        segment_duration: int
    ) -> List[Path]:
        """
        Split video into equal-length segments
        
        Args:
            input_path: Path to input video
            output_dir: Directory to save segments
            segment_duration: Length of each segment in seconds
            
        Returns:
            List of paths to created segment files
            
        Raises:
            subprocess.CalledProcessError: If ffmpeg fails
        """
        # Create output pattern (segment_000.mp4, segment_001.mp4, etc.)
        output_pattern = str(output_dir / "segment_%03d.mp4")
        
        # Build ffmpeg command
        cmd = [
            'ffmpeg',
            '-i', input_path,              # Input file
            '-c', 'copy',                  # Copy codec (no re-encoding = FAST!)
            '-map', '0',                   # Map all streams
            '-segment_time', str(segment_duration),  # Segment length
            '-f', 'segment',               # Output format: segment
            '-reset_timestamps', '1',      # Reset timestamps for each segment
            output_pattern                 # Output file pattern
        ]
        
        # Run ffmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Find all created segments
        segments = sorted(output_dir.glob("segment_*.mp4"))
        
        return segments
    
    @staticmethod
    def get_video_resolution(video_path: str) -> tuple:
        """
        Get video resolution (width, height)
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Tuple of (width, height)
        """
        info = FFmpegService.get_video_info(video_path)
        
        # Find video stream
        for stream in info['streams']:
            if stream['codec_type'] == 'video':
                return (stream['width'], stream['height'])
        
        return (0, 0)