import os
import re
import shutil
import subprocess
from argparse import ArgumentParser
from pathlib import Path

import yaml
from moviepy.editor import (
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)


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
    return args

def get_video_files_in_directory(directory):
    extensions = ['.MP4', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.MTS']  # Add or remove extensions as needed
    return sorted([file for file in directory.iterdir() if file.suffix in extensions])

def sanitize_filename(title):
    # Strip out reserved words for Windows
    title = re.sub(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(\.|$)', '_', title)
    
    # Replace reserved characters with underscore
    title = re.sub(r'[\/\\\?\%\*\:\|\\"\<\>\.]', '_', title)

    # Remove leading/trailing dots and spaces
    title = title.strip('. ')
    
    return title

class MergeVideo:
    def __init__(self, video_path) -> None:
        super().__init__()
        self.video_path: Path = video_path
        self.file_name = self.video_path.name
        self.file_ext = self.video_path.suffix
        self.fps: float = self.get_fps()
        self.mts_path = None
        if self.file_ext.lower().endswith('.mts'):
           self.convert_and_move()

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
        fps_fraction = result.stdout.decode('utf-8').strip()

        # Convert fps fraction to float
        fps_split = fps_fraction.split('/')
        if len(fps_split) == 3:
            numerator, derp, denominator = fps_split
        else:
            numerator, denominator = fps_split
        fps = float(numerator) / float(denominator)
        return round(fps)

    def convert_mts_to_mp4(self):
        mts_path = self.video_path
        mp4_path = self.video_path.with_suffix(".mp4")
        cmd = ["ffmpeg", "-i", str(mts_path), "-vf", "'yadif'",  "-c:v", "libx265", "-c:a", "aac", str(mp4_path)]
        subprocess.run(cmd)
        return mp4_path
    
    def move_mts_to_subdir(self):
        mts_path = self.video_path

        # Get the directory containing the MTS file
        dir_path = mts_path.parent

        # Create a new sub-directory named 'Processed_MTS'
        processed_mts_dir = dir_path / "Processed_MTS"
        os.makedirs(processed_mts_dir, exist_ok=True)

        # Move the MTS file to the new sub-directory
        new_path = processed_mts_dir / mts_path.name
        shutil.move(mts_path, new_path)
        self.mts_path = new_path

    def convert_and_move(self):
        print(f"Converting .MTS file at {self.file_name} to .MP4...")
        mp4_path = self.convert_mts_to_mp4()
        
        print(f"Moving .MTS file at {self.file_name} to Processed_MTS")
        self.move_mts_to_subdir()
        self.video_path = mp4_path

def main():
    # Arguments
    arguments = getArguments()

    input_directory = Path(arguments.input)
    output_directory = Path(arguments.output)
    years_list = arguments.years.split(",")
    threads = arguments.threads

    # First, loop through each year sub-directory
    for year_directory in input_directory.iterdir():
        if year_directory.is_dir() and year_directory.name in years_list:  # Check if directory name represents a year and is in years_list
            # Loop through each sub-directory inside the year directory
            for sub_directory in year_directory.iterdir():
                if sub_directory.is_dir():
                    title = ""
                    description = ""

                    # Split the sub-directory name to check for date and title
                    parts = sub_directory.name.split(' - ')
                    filmed_date = parts[0].strip()
                    title = parts[1] if len(parts) > 1 else ""

                    # If still no title, print an error and continue to the next directory
                    if not title:
                        print(f"Error: No title found for directory {sub_directory}. Skipping...")
                        continue
                    title = sanitize_filename(title)
                    
                    # If no Description in info.yaml, use the title as description
                    if not description and title:
                        description = title
                
                    # Parse date from directory name and create output filename
                    output_file_name = f"{filmed_date} - {title}.mp4"
                    temp_output_file_path = output_directory / f"temp_{output_file_name}"
                    final_output_file_path = output_directory / output_file_name

                    # Check if the merged movie already exists
                    if final_output_file_path.exists():
                        print(f"File {final_output_file_path} already exists. Skipping...")
                        continue

                    video_files_tmp = get_video_files_in_directory(sub_directory)
                    video_files = []
                    for file in video_files_tmp:
                        obj = MergeVideo(video_path=file)
                        video_files.append(obj)

                    # Burn title into the first video
                    print("Burning title into first clip")
                    first_clip = VideoFileClip(str(video_files[0].video_path))
                    width, height = first_clip.size

                    # Create the main text clip
                    txt_clip = TextClip(title, fontsize=70, color='white', font="Arial").set_duration(5)
                    # shadow_clip = TextClip(title, fontsize=70, color='gray', font="Arial").set_duration(5)
                    
                    # Create the shadow text clip
                    offset = 1
                    # Positioning the clips
                    txt_position = ('center', 'center')
                    # shadow_position = (width/2 + offset, height/2 + offset)
                    txt_clip = txt_clip.set_position(txt_position)
                    # shadow_clip = shadow_clip.set_position(shadow_position)

                    # Apply the fade out effect
                    fade_duration = 2  # Duration in seconds
                    txt_clip = txt_clip.crossfadeout(fade_duration)
                    # shadow_clip = shadow_clip.crossfadeout(fade_duration)

                    video_with_text = CompositeVideoClip([first_clip, txt_clip])
                    # first_clip = concatenate_videoclips([first_clip.crossfadein(0.5).set_duration(first_clip.duration - 0.5), txt_clip.crossfadeout(0.5).set_duration(0.5)], method="compose")

                    clips = [VideoFileClip(str(video_file.video_path)) if not isinstance(video_file.video_path, VideoFileClip) else video_file.video_path for video_file in video_files]
                    clips[0] = video_with_text
                    final_clip = concatenate_videoclips(clips, method="compose")

                    # Get the FPS from the first video in the list
                    output_fps = video_files[0].fps

                    # When writing the output video:
                    print(f"Writing file {final_output_file_path}. FPS: {output_fps}")
                    final_clip.write_videofile(
                        str(temp_output_file_path), 
                        fps=output_fps, 
                        codec='libx265',
                        threads=threads,
                        ffmpeg_params=[
                            "-metadata", f"title={title}",
                            "-metadata", f"description={description}",
                            "-metadata", f"creation_time={filmed_date}T00:00:00"  # Setting time to midnight. Adjust if you have precise time.
                        ]
                    )

                    # Rename the temporary file to its final name
                    temp_output_file_path.rename(final_output_file_path)

if __name__ == '__main__':
    main()