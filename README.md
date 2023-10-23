# movie-merge

## Summary

This script takes a folder as input and walks through that folder looking for a specific folder structure. When a folder that only contains digits is found the script continues walking and looking for a folder starting with a date "ex. 2017-01-01" and ending with a title.

Example:

```ascii
input_directory/
    |
    |-- 2017/
    |   |-- 2017-01-01 - title1/
    |   |   |-- info.yaml
    |   |   |-- video1.mp4
    |   |   |-- video2.mp4
    |   |
    |   |-- 2017-02-01 - title2/
    |       |-- info.yaml
    |       |-- video1.mp4
    |
    |-- 2018/
    |-- 2019/
    .
    .
    .
```

The script expects every folder with a `date` and `title` to contains a bunch of videos. These videos will be concatenated into one single movie and save to the given output.
It also converts `mts` files to `mp4`. Mts videos can be difficult to process unless normalized beforehand.

The `info.yaml` is optional.

## Build

```shell
docker buildx build --load \
--platform linux/amd64 \
--tag emil-jacero/movie-merge:dev .
```

## Run

```shell
docker run --rm -it -v /path/to/video-files/directory:/input -v /path/to/video-files/directory:/output emil-jacero/movie-merge:dev -i /input -o /output -y "2017,2018" -t 2
```
