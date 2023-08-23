import os
import re
from argparse import ArgumentParser
from pathlib import Path

import yaml
from moviepy.editor import TextClip, VideoFileClip, concatenate_videoclips


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

def main():
    # Arguments
    arguments = getArguments()

    input_directory = Path(arguments.input)
    output_directory = Path(arguments.output)

    for sub_directory in input_directory.iterdir():
        if sub_directory.is_dir():
            # Parse YAML file
            yaml_path = sub_directory / "info.yaml"
            if yaml_path.exists():
                with open(yaml_path, 'r') as file:
                    data = yaml.safe_load(file)
                    title = data.get("Title", "")
                    title = sanitize_filename(title)
                    description = data.get("Description", "")

                    # Get video files
                    video_files = get_video_files_in_directory(sub_directory)

                    # # Burn title into the first video
                    # first_clip = VideoFileClip(str(video_files[0]))
                    # txt_clip = TextClip(title, fontsize=50, color='white').set_pos('center').set_duration(first_clip.duration)
                    # first_clip = concatenate_videoclips([first_clip.crossfadein(0.5).set_duration(first_clip.duration - 0.5), txt_clip.crossfadeout(0.5).set_duration(0.5)], method="compose")

                    # # Replace the original first video with the modified one
                    # video_files[0] = first_clip

                    clips = [VideoFileClip(str(video_file)) if not isinstance(video_file, VideoFileClip) else video_file for video_file in video_files]
                    final_clip = concatenate_videoclips(clips, method="compose")
                    
                    # Parse date from directory name and create output filename
                    date_str_lst = sub_directory.name.split('-') # Assuming date is first component of directory name separated by '-'
                    date_str = f"{date_str_lst[0].strip(' ')}-{date_str_lst[1].strip(' ')}-{date_str_lst[2].strip(' ')}"
                    output_file_name = f"{date_str} - {title}.mp4"
                    # output_file_path = output_directory / output_file_name
                    temp_output_file_path = output_directory / f"temp_{output_file_name}"
                    final_output_file_path = output_directory / output_file_name

                    # Check if the final merged movie already exists
                    if final_output_file_path.exists():
                        print(f"File {final_output_file_path} already exists. Skipping...")
                        continue

                    # Write to a temporary file
                    final_clip.write_videofile(str(temp_output_file_path), codec='libx265', ffmpeg_params=["-metadata", f"description={description}"])

                    # Rename the temporary file to its final name after it's completely written
                    temp_output_file_path.rename(final_output_file_path)

    print("Merging complete!")

if __name__ == '__main__':
    main()