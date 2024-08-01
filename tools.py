### tools.py

import re
import subprocess
from argparse import ArgumentParser
from datetime import datetime
from logging import getLogger

import exifread
from moviepy.editor import CompositeVideoClip, TextClip, concatenate_videoclips

log = getLogger('movie-merge')

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
    extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mts']
    return sorted([file for file in directory.iterdir() if str(file.suffix).lower() in extensions])

def get_directory_info(sub_directory):
    # Skip if directory name is "ProcessedClips"
    if sub_directory.name == "ProcessedClips":
        return None, None, None, None

    # Extract the last component of the directory name
    dir_name = sub_directory.name
    
    # Attempt to split the directory name by ' - ' to separate the date and title
    parts = dir_name.split(' - ')
    log.debug(f"Parts: {parts}")
    
    # The first part should be the date
    filmed_date = parts[0].strip()
    log.debug(f"Filmed date: {filmed_date}")
    
    # Extract the year from the date
    filmed_year = filmed_date.split('-')[0]
    log.debug(f"Filmed year: {filmed_year}")
    
    # Validate the date format (basic validation assuming YYYY-MM-DD)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', filmed_date):
        return None, None, None, None
    
    # If no title is provided, set both title and nice_title to filmed_date
    if len(parts) == 1:
        title = filmed_date
        nice_title = filmed_date
        log.debug(f"Title: {title}, Nice title: {nice_title}")
    else:
        title = sanitize_filename(parts[1])
        nice_title = f"{filmed_date} - {title}"
        log.debug(f"Title: {title}, Nice title: {nice_title}")
    
    return title, nice_title, filmed_date, filmed_year

def create_title_card(title):
    log.info("Creating title card for new chapter with title: " + title)

    try:
        txt_clip = TextClip(title, fontsize=70, color='white', font="Arial").set_duration(5)
        txt_position = ('center', 'center')
        txt_clip = txt_clip.set_position(txt_position)

        # Apply fade-in and fade-out effects
        fade_duration = 2  # Duration in seconds
        txt_clip = txt_clip.crossfadein(fade_duration).crossfadeout(fade_duration)

        return txt_clip
    except Exception as e:
        raise RuntimeError(f"Failed to create title card for {title}.") from e

def burn_title_into_clip(video_clip, title):
    log.info("Burning title into first clip")

    try:
        txt_clip = TextClip(title, fontsize=70, color='white', font="Arial").set_duration(5)
        txt_position = ('center', 'center')
        txt_clip = txt_clip.set_position(txt_position)

        # Apply the fade out effect
        fade_duration = 2  # Duration in seconds
        txt_clip = txt_clip.crossfadeout(fade_duration)

        video_with_text = CompositeVideoClip([video_clip, txt_clip])
        return video_with_text
    except Exception as e:
        log.error(f"Failed to create video file with burned in text: {str(e)}")
        raise RuntimeError(f"Failed to create video file with burned in text.") from e

def concatenate_clips(video_clips, first_clip, title):
    log.debug("Merging video files")
    try:
        all_clips = [first_clip] + video_clips
        final_clip = concatenate_videoclips(all_clips, method="compose")
        return final_clip
    except Exception as e:
        log.error(f"Failed to create video clip from file {title}: {str(e)}")
        raise RuntimeError(f"Failed to create video clip from file {title}.") from e

def write_output_file(final_clip, output_file_path, output_fps, threads, title, filmed_date):
    final_clip.write_videofile(
        output_file_path, 
        fps=output_fps, 
        codec="libx264",
        preset="fast",
        threads=threads,
        write_logfile=False,
        ffmpeg_params=[
            "-metadata", f"title={title}",
            "-metadata", f"description={title}",
            "-metadata", f"creation_time={filmed_date}T00:00:00"  # Setting time to midnight. Adjust if you have precise time.
        ]
    )

def sort_clips_by_date(clips):
    for clip in clips:
        log.debug(f"Sorting clip: {clip.file_name}, creation_date: {clip.creation_date}, type: {type(clip.creation_date)}")
    return sorted(clips, key=lambda clip: clip.creation_date)
