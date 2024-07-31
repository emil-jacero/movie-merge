# tools.py

import json
import multiprocessing
import os
import re
import shutil
import subprocess
from argparse import ArgumentParser
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

from moviepy.editor import CompositeVideoClip, TextClip, VideoFileClip
from moviepy.video.fx.all import resize

log = getLogger()
logger_name = 'movie-merge-tools'

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

def resolution_mismatch(video_files):
    """
    Checks if all video files have the same resolution.
    Returns True if there's a mismatch.
    """
    resolutions = set()
    
    for video_file in video_files:
        clip = VideoFileClip(video_file.video_path_str())
        resolutions.add((clip.w, clip.h))
        clip.close()  # Close the clip to avoid consuming system resources.
    
    return len(resolutions) > 1  # Mismatch exists if we have more than one resolution.

def find_largest_resolution(video_files):
    max_width = 0
    max_height = 0
    
    for file in video_files:
        width, height = file.resolution
        if width > max_width:
            max_width = width
        if height > max_height:
            max_height = height
            
    return max_width, max_height

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
