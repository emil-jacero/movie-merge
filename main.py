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
from pathlib import Path

import yaml
from moviepy.editor import (
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

log = getLogger()
log.setLevel(DEBUG)
logger_name = 'movie-merge'
log_levels = {'DEBUG': DEBUG, 'INFO': INFO, 'WARNING': WARNING, 'ERROR': ERROR}
formatter = Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handlers = [StreamHandler()]

for handler in log_handlers:
    handler.setFormatter(fmt=formatter)  # Set Formatter
    log.addHandler(handler)  # Set Handler

log.debug(f'Loaded these handlers: {log_handlers}')

def validate_thread_count(user_thread_count):
    max_threads = multiprocessing.cpu_count()
    if user_thread_count >= max_threads:
        raise ValueError(f"Invalid thread count. The maximum available threads on this system is {max_threads}.")

def getArguments():
    name = 'movie-merge'
    version = '0.1.0'
    parser = ArgumentParser(
        description=f'{name}: Merge folders of videos into one single movie')

    parser.add_argument('-v',
                        '--version',
                        action='version',
                        version=f'{name} {version}',
                        help="Returns the version number and exit")

    parser.add_argument('-l',
                        '--log-level',
                        dest='log_level',
                        type=str,
                        default='INFO',
                        help='Set log level (Default: INFO)')

    parser.add_argument('-i',
                        '--input-dir',
                        dest='input',
                        type=str,
                        default='',
                        help='Input directory')

    parser.add_argument('-o',
                        '--output-dir',
                        dest='output',
                        type=str,
                        default='',
                        help='Output directory')

    parser.add_argument('-y',
                        '--years',
                        dest='years',
                        type=str,
                        default='',
                        help='Comma separated list of years to process.')

    parser.add_argument('-t',
                        '--threads',
                        dest='threads',
                        type=str,
                        default='1',
                        help='Number of threads to use for ffmpeg. Can speed up the writing of the video on multicore computers.')

    args = parser.parse_args()
    try:
        validate_thread_count(int(args.threads))
    except ValueError as error:
        log.error(error)
        exit(1)
    return args

class MergeVideo:
    def __init__(self, video_path, threads) -> None:
        super().__init__()
        self.video_path: Path = video_path
        self.file_name = self.video_path.name
        self.file_ext = self.video_path.suffix
        self.fps: float = self.get_fps()
        self.mts_path = None
        if self.file_ext.lower().endswith('.mts'):
           self.convert_and_move(threads)

    def get_fps(self):
        cmd = [
            'ffprobe', 
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=avg_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(self.video_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError(f"Command '{' '.join(cmd)}' failed with error code {result.returncode}.")
        fps_fraction = result.stdout.decode('utf-8').strip()

        # Convert fps fraction to float
        fps_split = fps_fraction.split('/')
        if len(fps_split) == 3:
            numerator, derp, denominator = fps_split
        else:
            numerator, denominator = fps_split
        fps = float(numerator) / float(denominator)
        return round(fps)

    def move_mts_to_subdir(self):
        mts_path = self.video_path

        # Get the directory containing the MTS file
        dir_path = mts_path.parent

        # Create a new sub-directory named 'Processed_MTS'
        processed_mts_dir = dir_path / "Processed_MTS"
        os.makedirs(processed_mts_dir, exist_ok=True)

        # Move the MTS file to the new sub-directory
        new_path = processed_mts_dir / mts_path.name
        try:
            shutil.move(mts_path, new_path)
        except OSError as e:
            raise RuntimeError(f"Failed to move file from {mts_path} to {new_path}.") from e
        self.mts_path = new_path

    def convert_and_move(self, threads=1):
        log.info(f"Converting .MTS file at {self.file_name} to .MP4...")
        mts_path = self.video_path
        mp4_path = self.video_path.with_suffix(".mp4")
        cmd = ["ffmpeg", "-i", str(mts_path), "-vf", "'yadif'",  "-c:v", "libx265", "-c:a", "aac", "-threads", str(threads), str(mp4_path)]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Command '{' '.join(cmd)}' failed with error code {result.returncode}.")
        
        log.info(f"Moving .MTS file at {self.file_name} to Processed_MTS")
        self.move_mts_to_subdir()
        self.video_path = mp4_path
    
    def video_path_str(self):
        return str(self.video_path)

def get_video_files_in_directory(directory):
    extensions = ['.MP4', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.mts']  # Add or remove extensions as needed
    return sorted([file for file in directory.iterdir() if str(file.suffix).lower() in extensions])

def sanitize_filename(title):
    """Sanitize the filename by replacing reserved words and characters."""
    
    # Strip out reserved words for Windows
    title = re.sub(r'(?i)\b(con|prn|aux|nul|com[0-9]|lpt[0-9])\b', '_', title)

    # Replace reserved characters with underscore
    title = re.sub(r'[\/\\\?\%\*\:\|\\"\<\>\.]', '_', title)

    # Remove leading/trailing dots and spaces
    title = title.strip('. ')

    return title

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

def get_video_files(sub_directory, threads):
    log.debug("Gathering video files")
    video_files_tmp = get_video_files_in_directory(sub_directory)
    str_files = [file.name for file in video_files_tmp]
    log.debug(json.dumps(str_files))

    video_files = []
    for file in video_files_tmp:
        obj = MergeVideo(video_path=file, threads=threads)
        video_files.append(obj)
    return video_files

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

def concatenate_clips(video_files, first_clip, title):
    log.debug("Merging video files")
    clips = [VideoFileClip(video_file.video_path_str()) for video_file in video_files]
    clips[0] = first_clip
    try:
        final_clip = concatenate_videoclips(clips, method="compose")
    except Exception as e:
        # raise Exception(e)
        raise RuntimeError(f"Failed to create video clip from file {title}.") from e
    return final_clip

def write_output_file(final_clip, output_file_path, output_fps, threads, title, description, filmed_date):
    final_clip.write_videofile(
        output_file_path, 
        fps=output_fps, 
        codec='libx264',
        threads=threads,
        ffmpeg_params=[
            "-metadata", f"title={title}",
            "-metadata", f"description={description}",
            "-metadata", f"creation_time={filmed_date}T00:00:00"  # Setting time to midnight. Adjust if you have precise time.
        ]
    )

def process_directory(sub_directory, output_directory, threads):
    title, description, filmed_date, filmed_year = get_directory_info(sub_directory)
    if get_directory_info is None:
        log.error(f"No title found for directory {sub_directory}. Skipping...")
        return

    nice_title = f"{filmed_year} - {title}"
    output_file_name = f"{filmed_date} - {title}.mp4"
    temp_output_file_path = output_directory / f"temp_{output_file_name}"
    final_output_file_path = output_directory / output_file_name

    if final_output_file_path.exists():
        log.info(f"File {final_output_file_path} already exists. Skipping...")
        return

    log.info(f"Processing movie {filmed_date} - {title}")

    video_files = get_video_files(sub_directory, threads)
    first_clip = burn_title_into_first_clip(video_files[0], nice_title)
    final_clip = concatenate_clips(video_files, first_clip, nice_title)

    output_fps = video_files[0].fps
    log.info(f"Writing file {final_output_file_path}. FPS: {output_fps}")
    write_output_file(
        final_clip,
        str(temp_output_file_path),
        output_fps,
        threads,
        nice_title,
        description,
        filmed_date
    )

    temp_output_file_path.rename(final_output_file_path)

def main():
    arguments = getArguments()
    if arguments.log_level in log_levels.keys():
        log_level = log_levels[arguments.log_level]
    else:
        log_level = INFO

    log.setLevel(log_level)

    input_directory = Path(arguments.input)
    output_directory = Path(arguments.output)
    years_list = [year.strip() for year in arguments.years.split(",") if year.strip()]
    sorted_years_list = sorted(years_list, key=lambda x: (x.isdigit(), x))
    threads = arguments.threads

    if not input_directory.exists():
        raise FileNotFoundError(f"Input directory {input_directory} does not exist.")
    if not output_directory.exists():
        raise FileNotFoundError(f"Output directory {output_directory} does not exist.")
    if not sorted_years_list:
        raise ValueError("The year list is empty.")

    for year_directory in input_directory.iterdir():
        if year_directory.is_dir() and year_directory.name in sorted_years_list:
            for sub_directory in year_directory.iterdir():
                if sub_directory.is_dir():
                    try:
                        process_directory(sub_directory, output_directory, threads)
                    except Exception as e:
                        log.error(f"Error processing directory {sub_directory}: {e}")


if __name__ == '__main__':
    main()
