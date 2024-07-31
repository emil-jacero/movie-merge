# main.py

import json
import multiprocessing
import os
import re
import shutil
import subprocess
from argparse import ArgumentParser
from logging import DEBUG, ERROR, INFO, WARNING, Formatter, StreamHandler, getLogger
from pathlib import Path

from moviepy.editor import VideoFileClip, concatenate_videoclips

# Setup logging
log = getLogger('movie-merge')
logger_name = 'movie-merge'
log_levels = {'DEBUG': DEBUG, 'INFO': INFO, 'WARNING': WARNING, 'ERROR': ERROR}

# Default log level setup
log.setLevel(DEBUG)  # Set the default level to DEBUG to allow filtering later
stream_handler = StreamHandler()
formatter = Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler.setFormatter(formatter)
log.addHandler(stream_handler)

from tools import (
    burn_title_into_first_clip,
    find_largest_resolution,
    get_directory_info,
    get_video_files_in_directory,
    resolution_mismatch,
)


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

class Clip:
    def get_creation_date(self):
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format_tags=creation_time',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(self.video_path)
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError(f"Command '{' '.join(cmd)}' failed with error code {result.returncode}.")
        
        creation_date = result.stdout.decode('utf-8').strip()
        return creation_date

    def __init__(self, video_path, threads) -> None:
        super().__init__()
        self.video_path: Path = video_path
        self.file_name = self.video_path.name
        self.file_ext = self.video_path.suffix
        self.resolution: tuple = self.get_resolution()
        self.fps: float = self.get_fps()
        self.target_resolution = (1920, 1080)
        self.mts_path = None
        self.creation_date = self.get_creation_date()
        if self.file_ext.lower().endswith('.mts'):
           self.convert_and_move(threads)
        else:
            self.resize_video(self.target_resolution)  # Always resize to target resolution

    def get_resolution(self):
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            str(self.video_path)
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError(f"Command '{' '.join(cmd)}' failed with error code {result.returncode}.")
        output = result.stdout.decode('utf-8').strip()
        try:
            # Split output by lines and use the first non-empty line
            first_line = next(line for line in output.splitlines() if line.strip())
            width, height = map(int, first_line.split(","))
        except ValueError:
            raise ValueError(f"Unexpected output format from ffprobe: {output}")
        return (width, height)

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

    def resize_video(self, target_resolution):
        target_width, target_height = target_resolution
        current_width, current_height = self.resolution

        # Check if the current resolution is already 1920x1080
        if current_width == target_width and current_height == target_height:
            log.debug(f"Skipping resize for {self.file_name}, already 1920x1080.")
            return

        resized_path = self.video_path.with_name(f"resized_{self.video_path.name}")

        cmd = [
            'ffmpeg',
            '-i', str(self.video_path),
            '-vf', f'scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2',
            '-c:a', 'copy',
            str(resized_path)
        ]

        result = subprocess.run(cmd)

        if result.returncode != 0:
            raise RuntimeError(f"Command '{' '.join(cmd)}' failed with error code {result.returncode}.")

        self.video_path = resized_path
        log.debug(f"Resized {self.file_name} to {target_width}x{target_height}")

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
        cmd = [
            "ffmpeg", 
            "-y",  # Overwrite output files without asking
            "-i", str(mts_path), 
            "-vf", "'yadif'",  
            "-c:v", "libx264",  # Use H.264 codec
            "-c:a", "aac", 
            "-threads", str(threads), 
            str(mp4_path)
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Command '{' '.join(cmd)}' failed with error code {result.returncode}.")

        log.info(f"Moving .MTS file at {self.file_name} to Processed_MTS")
        self.move_mts_to_subdir()
        self.video_path = mp4_path
        self.resize_video(self.target_resolution)  # Resize to target resolution after conversion

    def video_path_str(self):
        return str(self.video_path)

    def delete_video(self):
        os.remove(self.video_path)

    def output_data(self):
        return { "video_path": f"{self.video_path}", "file_name": f"{self.file_name}", "file_ext": f"{self.file_ext}", "resolution": f"{self.resolution}", "fps": f"{self.fps}", "mts_path": f"{self.mts_path}"}

def get_video_files(sub_directory, threads):
    log.debug("Gathering video files")
    video_files_tmp = get_video_files_in_directory(sub_directory)

    video_files = []
    for file in video_files_tmp:
        obj = Clip(video_path=file, threads=threads)
        video_files.append(obj)
        log.debug(obj.output_data())
    return video_files

def concatenate_clips(clips, title):
    log.debug("Merging video files")

    try:
        final_clip = concatenate_videoclips(clips, method="compose")
        return final_clip
    except Exception as e:
        raise RuntimeError(f"Failed to create video clip from file {title}.") from e

# def process_directory(sub_directory, output_directory, threads):
#     title, description, filmed_date, filmed_year = get_directory_info(sub_directory)
#     if not title:
#         log.error(f"No title found for directory {sub_directory}. Skipping...")
#         return

#     nice_title = f"{filmed_year} - {title}"
#     output_file_name = f"{filmed_date} - {title}.mp4"
#     temp_output_file_path = output_directory / f"temp_{output_file_name}"
#     final_output_file_path = output_directory / output_file_name

#     if final_output_file_path.exists():
#         log.info(f"File {final_output_file_path} already exists. Skipping...")
#         return

#     log.info(f"Processing movie '{nice_title}' from directory {sub_directory}")

#     video_files = get_video_files(sub_directory, threads)
#     sorted_video_files = sort_clips_by_date(video_files)
#     rename_clips(sorted_video_files)

#     # Only log detailed clip info if at debug level
#     if log.getEffectiveLevel() == DEBUG:
#         for clip in sorted_video_files:
#             log.debug(f"Working on clip: {clip.file_name} with path: {clip.video_path}")
#     else:
#         for clip in sorted_video_files:
#             log.info(f"Processing clip: {clip.file_name}")

#     intro_clip = burn_title_into_first_clip(video_files[0], nice_title)
#     clips = [VideoFileClip(video_file.video_path_str()) for video_file in video_files]
#     clips.insert(0, intro_clip)
#     final_clip = concatenate_clips(clips, nice_title)

#     output_fps = video_files[0].fps
#     log.info(f"Writing file {final_output_file_path}. FPS: {output_fps}")
#     write_output_file(
#         final_clip,
#         str(temp_output_file_path),
#         output_fps,
#         threads,
#         nice_title,
#         description,
#         filmed_date
#     )

#     temp_output_file_path.rename(final_output_file_path)

def write_output_file(final_clip, output_file_path, output_fps, threads, title, description, filmed_date):
    final_clip.write_videofile(
        output_file_path, 
        fps=output_fps, 
        codec="libx264",
        preset="fast",
        threads=threads,
        write_logfile=False,
        ffmpeg_params=[
            "-metadata", f"title={title}",
            "-metadata", f"description={description}",
            "-metadata", f"creation_time={filmed_date}T00:00:00"  # Setting time to midnight. Adjust if you have precise time.
        ]
    )

def sort_clips_by_date(clips):
    return sorted(clips, key=lambda clip: clip.creation_date)

def rename_clips(clips):
    for index, clip in enumerate(clips):
        # Check if the file is already renamed according to the pattern
        if re.match(r"^\d{4}_", clip.file_name):
            log.info(f"File {clip.file_name} is already renamed, skipping.")
            continue

        # Generate the new filename with a four-digit number and the original file name
        new_file_name = f"{index+1:04d}_{clip.file_name}"
        new_file_path = clip.video_path.with_name(new_file_name)

        # Rename the file in place
        os.rename(clip.video_path, new_file_path)

        # Update the clip's video_path to the new path
        clip.video_path = new_file_path

        log.info(f"Renamed file {clip.file_name} to {new_file_name}")

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
    threads = int(arguments.threads)

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
                        video_files = get_video_files(sub_directory, threads)
                        sorted_video_files = sort_clips_by_date(video_files)
                        rename_clips(sorted_video_files)  # Rename first based on sorted order

                        # Start processing clips
                        log.info(f"Starting processing for directory {sub_directory}")
                        process_directory(sub_directory, output_directory, threads)
                    except Exception as e:
                        log.error(f"Error processing directory {sub_directory}: {e}")

def process_directory(sub_directory, output_directory, threads):
    title, description, filmed_date, filmed_year = get_directory_info(sub_directory)
    if not title:
        log.error(f"No title found for directory {sub_directory}. Skipping...")
        return

    nice_title = f"{filmed_year} - {title}"
    output_file_name = f"{filmed_date} - {title}.mp4"
    temp_output_file_path = output_directory / f"temp_{output_file_name}"
    final_output_file_path = output_directory / output_file_name

    if final_output_file_path.exists():
        log.info(f"File {final_output_file_path} already exists. Skipping...")
        return

    log.info(f"Processing movie '{nice_title}' from directory {sub_directory}")

    video_files = get_video_files(sub_directory, threads)  # Already renamed and sorted
    intro_clip = burn_title_into_first_clip(video_files[0], nice_title)
    clips = [VideoFileClip(video_file.video_path_str()) for video_file in video_files]
    clips.insert(0, intro_clip)
    final_clip = concatenate_clips(clips, nice_title)

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

if __name__ == '__main__':
    main()
