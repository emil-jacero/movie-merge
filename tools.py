# tools.py

import json
import multiprocessing
import os
import re
import shutil
import subprocess
from argparse import ArgumentParser
from datetime import datetime
from logging import (
    DEBUG,
    ERROR,
    INFO,
    WARNING,
    FileHandler,
    Formatter,
    StreamHandler,
    getLogger,
)
from pathlib import Path

import exifread
from moviepy.editor import CompositeVideoClip, TextClip, VideoFileClip
from moviepy.video.fx.all import resize

log = getLogger()
logger_name = 'movie-merge-tools'

def extract_datetime(file_path):
    """
    Extracts the datetime from the metadata of a file.
    First attempts to use the file's creation date from metadata, then falls back to EXIF data.
    """
    def get_creation_date_from_metadata(file_path):
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'format_tags=creation_time', '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def get_creation_date_from_exif(file_path):
        with open(file_path, 'rb') as f:
            tags = exifread.process_file(f)
            date_tag = tags.get('EXIF DateTimeOriginal') or tags.get('Image DateTime')
            if date_tag:
                return date_tag.values
        return None

    # Attempt to extract creation date from metadata
    creation_date = get_creation_date_from_metadata(file_path)
    if creation_date:
        try:
            return datetime.fromisoformat(creation_date)
        except ValueError:
            pass  # Handle incorrect format if necessary

    # Fallback to extracting date from EXIF data
    exif_date = get_creation_date_from_exif(file_path)
    if exif_date:
        try:
            return datetime.strptime(exif_date, '%Y:%m:%d %H:%M:%S')
        except ValueError:
            pass  # Handle incorrect format if necessary

    # Final fallback to file's modification time
    return datetime.fromtimestamp(file_path.stat().st_mtime)

def sanitize_filename(title):
    """Sanitize the filename by replacing reserved words and characters."""
    
    # Strip out reserved words for Windows
    title = re.sub(r'(?i)\b(con|prn|aux|nul|com[0-9]|lpt[0-9])\b', '_', title)

    # Replace reserved characters with underscore
    title = re.sub(r'[\/\\\?\%\*\:\|\\"\<\>\.]', '_', title)

    # Remove leading/trailing dots and spaces
    title = title.strip('. ')

    return title

def get_video_files_in_directory(directory):
    extensions = ['.MP4', '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mts']  # Add or remove extensions as needed
    return sorted([file for file in directory.iterdir() if str(file.suffix).lower() in extensions])

def get_directory_info(sub_directory):
    # Split the sub-directory name to check for date and title
    parts = sub_directory.name.split(' - ')
    filmed_date = parts[0].strip()
    if len(parts) == 3:
        title = f"{ parts[1]} - { parts[2]}"
    elif len(parts) == 2:
        title = parts[1]
    else:
        title = None
    filmed_year = (parts[0].strip()).split('-')[0]
    
    if not title:
        return
    title = sanitize_filename(title)
    description = title  # Set the description to same as title, for now
    return title, description, filmed_date, filmed_year

def burn_title_into_first_clip(video_file, title):
    log.info("Burning title into first clip")

    # Create the main text clip
    try:
        first_clip = VideoFileClip(str(video_file.video_path))
        txt_clip = TextClip(title, fontsize=70, color='white', font="Arial").set_duration(5)
        txt_position = ('center', 'center')
        txt_clip = txt_clip.set_position(txt_position)

        # Apply the fade out effect
        fade_duration = 2  # Duration in seconds
        txt_clip = txt_clip.crossfadeout(fade_duration)

        video_with_text = CompositeVideoClip([first_clip, txt_clip])
    except Exception as e:
        # raise Exception(e)
        raise RuntimeError(f"Failed to create video file with burned in text from file {str(video_file.video_path)}.") from e

    return video_with_text
