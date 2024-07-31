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
    extract_datetime,
    get_directory_info,
    get_video_files_in_directory,
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
    def __init__(self, video_path, threads=1) -> None:
        self.video_path = Path(video_path)
        self.file_name = self.video_path.name
        self.file_ext = self.video_path.suffix
        self.resolution = self.get_resolution()
        self.fps = self.get_fps()
        self.target_resolution = (1920, 1080)
        self.mts_path = None
        self.creation_date = extract_datetime(self.video_path)  # Use extract_datetime
        
        if self.file_ext.lower() == '.mts':
            self.convert_and_move(threads)
        else:
            self.resize_video()

    def run_ffmpeg(self, cmd, description):
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in process.stderr:
            self.process_ffmpeg_log(line)
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"Failed {description} for {self.file_name}")

    def run_ffmpeg_and_get_output(self, cmd, description):
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            log.error(f"Failed {description} for {self.file_name}")
            raise RuntimeError(f"Failed {description} for {self.file_name}")
        return result.stdout.strip()

    def process_ffmpeg_log(self, line):
        line = line.strip()
        if not line:
            return
        
        if "error" in line.lower():
            log.error(line)
        elif "warning" in line.lower():
            log.warning(line)
        elif re.match(r"frame=.*fps=.*q=.*size=.*time=.*bitrate=.*speed=.*", line):
            log.info(line)
        else:
            log.debug(line)

    def get_creation_date(self):
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format_tags=creation_time',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(self.video_path)
        ]
        creation_date = self.run_ffmpeg_and_get_output(cmd, "creation date extraction")
        return creation_date

    def get_resolution(self):
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
            'stream=width,height', '-of', 'csv=p=0', str(self.video_path)
        ]
        output = self.run_ffmpeg_and_get_output(cmd, "resolution extraction")
        
        try:
            # Split the output into lines and find the first non-empty line
            lines = output.splitlines()
            for line in lines:
                # Remove whitespace and skip empty lines
                line = line.strip()
                if line:
                    # Attempt to parse the first non-empty line as resolution
                    width, height = map(int, line.split(','))
                    return width, height

            raise ValueError(f"No valid resolution found in ffprobe output: {output}")
        except ValueError as ve:
            # Log the error and re-raise with more context if needed
            log.error(f"Error parsing resolution from ffprobe output: {output}")
            raise ve

    def get_fps(self):
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate', '-of', 'json', str(self.video_path)
        ]
        result = self.run_ffmpeg_and_get_output(cmd, "FPS extraction")

        try:
            # Parse the JSON output
            result_json = json.loads(result)
            r_frame_rate = result_json['streams'][0]['r_frame_rate']
            
            # Calculate the FPS from the fraction
            num, denom = map(int, r_frame_rate.split('/'))
            fps = num / denom
            
            # Safely round to the nearest integer
            rounded_fps = round(fps)
            
            return rounded_fps
        except (ValueError, KeyError, IndexError, ZeroDivisionError) as e:
            log.error(f"Error parsing FPS from ffprobe output: {result}")
            raise ValueError(f"Unexpected FPS format from ffprobe: {result}") from e

    def resize_video(self):
        if self.resolution == self.target_resolution:
            log.debug(f"{self.file_name} already at target resolution.")
            return

        resized_path = self.video_path.with_name(f"resized_{self.file_name}")
        cmd = [
            'ffmpeg', '-i', str(self.video_path),
            '-vf', f'scale={self.target_resolution[0]}:{self.target_resolution[1]}:force_original_aspect_ratio=decrease',
            '-c:a', 'copy', str(resized_path)
        ]
        self.run_ffmpeg(cmd, "resizing")
        self.video_path = resized_path

    def convert_and_move(self, threads):
        log.info(f"Converting {self.file_name} to .mp4...")
        mp4_path = self.video_path.with_suffix('.mp4')
        cmd = [
            'ffmpeg', '-y', '-i', str(self.video_path), '-vf', 'yadif',
            '-c:v', 'libx264', '-c:a', 'aac', '-threads', str(threads),
            str(mp4_path)
        ]
        self.run_ffmpeg(cmd, "conversion")
        self.move_mts_to_subdir()
        self.video_path = mp4_path

    def move_mts_to_subdir(self):
        mts_path = self.video_path

        dir_path = mts_path.parent
        processed_mts_dir = dir_path / "Processed_MTS"
        os.makedirs(processed_mts_dir, exist_ok=True)

        new_path = processed_mts_dir / mts_path.name
        try:
            shutil.move(mts_path, new_path)
        except OSError as e:
            raise RuntimeError(f"Failed to move file from {mts_path} to {new_path}.") from e
        self.mts_path = new_path

    def video_path_str(self):
        return str(self.video_path)

    def delete_video(self):
        os.remove(self.video_path)

    def output_data(self):
        return { "video_path": f"{self.video_path}", "file_name": f"{self.file_name}", "file_ext": f"{self.file_ext}", "resolution": f"{self.resolution}", "fps": f"{self.fps}", "mts_path": f"{self.mts_path}"}

def rename_file(file, index):
    # Rename the file with a four-digit number prefix
    if not re.match(r"^\d{4}_", file.name):
        new_file_name = f"{index + 1:04d}_{file.name}"
        new_file_path = file.with_name(new_file_name)
        os.rename(file, new_file_path)
        log.info(f"Renamed file {file.name} to {new_file_name}")
        return new_file_path
    return file  # Return the original file path if no renaming was done

def get_video_files(sub_directory, threads):
    log.debug("Gathering video files")
    video_files_tmp = get_video_files_in_directory(sub_directory)

    video_files = []
    for file in video_files_tmp:
        obj = Clip(video_path=file, threads=threads)
        video_files.append(obj)

        # One-line INFO summary for each clip
        mts_info = f", Converted .mts to .mp4, Moved original to {obj.mts_path}" if obj.mts_path else ""
        log.info(f"Processed Clip: {obj.file_name}, Path: {obj.video_path}, Resolution: {obj.resolution}, FPS: {obj.fps}{mts_info}")

    sorted_video_files = sort_clips_by_date(video_files)

    for index, obj in enumerate(sorted_video_files):
        renamed_file = rename_file(obj.video_path, index)
        obj.video_path = renamed_file  # Update the video_path of the Clip object
        obj.file_name = renamed_file.name  # Update the file_name of the Clip object

        log.debug(obj.output_data())

    return sorted_video_files

def concatenate_clips(clips, title):
    log.debug("Merging video files")

    try:
        final_clip = concatenate_videoclips(clips, method="compose")
        return final_clip
    except Exception as e:
        raise RuntimeError(f"Failed to create video clip from file {title}.") from e

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

    # Sort and rename clips
    video_files = get_video_files(sub_directory, threads)

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

    log.info("Starting job with the following parameters:")
    log.info(f"Input Directory: {input_directory}")
    log.info(f"Output Directory: {output_directory}")
    log.info(f"Years to Process: {', '.join(sorted_years_list)}")
    log.info(f"Number of Threads: {threads}")

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